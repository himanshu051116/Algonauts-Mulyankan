"""Safety-focused, network-free v8 contract suite. No real PG assertions."""
from __future__ import annotations
import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path

from sqlalchemy import Column, MetaData, String, Table
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.schema import CreateIndex

ROOT=Path(__file__).resolve().parents[1]
BACKEND=ROOT/'payload/backend'
for name in ['app','app.database','app.models','app.models.riskops_operation','app.services']:
    if name not in sys.modules:
        m=types.ModuleType(name)
        m.__path__=[str(BACKEND/'app'),str(BACKEND/'app/models'),str(BACKEND/'app/services')]
        sys.modules[name]=m
class Base(DeclarativeBase):pass
base=types.ModuleType('app.base');base.Base=Base;sys.modules['app.base']=base
Table('users',Base.metadata,Column('id',String,primary_key=True))
Table('dispute_cases',Base.metadata,Column('id',String,primary_key=True))
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module
    spec.loader.exec_module(module)
    return module
model=load('app.models.riskops_operation',BACKEND/'app/models/riskops_operation.py')
class Result:
    def __init__(self,value=None,rows=()):self.value=value;self.rows=rows
    def scalar_one_or_none(self):return self.value
    def scalars(self):return self.rows
class Store:
    def __init__(self):self.rows={};self.sql=[];self.fail_commit=False
class FakeSession:
    def __init__(self,store):self.store=store
    async def __aenter__(self):return self
    async def __aexit__(self,*a):return False
    async def execute(self,stmt):
        compiled=stmt.compile(dialect=postgresql.dialect())
        sql=str(compiled);params=compiled.params;self.store.sql.append(sql)
        if sql.startswith('INSERT INTO riskops_provider_operations'):
            case_id=params['case_id'];key=params['operation_key']
            if key in self.store.rows or any(
                row.case_id==case_id and row.status in ('reserved','observed','ambiguous')
                for row in self.store.rows.values()
            ):return Result(None)
            self.store.rows[key]=types.SimpleNamespace(
                id=params['id'],operation_key=key,case_id=case_id,
                owner_id=params['owner_id'],operation_type=params['operation_type'],
                status=params['status'],evidence_type=params.get('evidence_type'),
                content_sha256=params.get('content_sha256'),
                provider_reference=None,domain_reference=None,error_code=None,created_at=None)
            return Result(params['id'])
        if sql.startswith('UPDATE riskops_provider_operations'):
            row=next((r for r in self.store.rows.values() if r.id==params.get('id_1')),None)
            permitted=params.get('status_1') or params.get('status_2') or []
            if not row or row.owner_id!=params.get('owner_id_1') or row.status not in permitted:
                return Result(None)
            for name in ('status','provider_reference','domain_reference','error_code'):
                if name in params:setattr(row,name,params[name])
            return Result(row.id)
        if sql.startswith('SELECT'):
            return Result(rows=[r for r in self.store.rows.values() if r.case_id==params.get('case_id_1') and r.owner_id==params.get('owner_id_1')])
        raise AssertionError('Unexpected SQL '+sql)
    async def commit(self):
        if self.store.fail_commit:raise RuntimeError('DB unavailable')
store=Store()
sys.modules['app.database'].async_session_factory=lambda:FakeSession(store)
journal=load('app.services.riskops_operation_journal',BACKEND/'app/services/riskops_operation_journal.py')

class GateTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        store.rows.clear();store.sql.clear();store.fail_commit=False
        self.j=journal.OperationJournal(factory=lambda:FakeSession(store))
    async def upload(self,case,contents):
        return await self.j.reserve(case_id=case,owner_id='merchant-owner',operation_type='evidence_upload',evidence_type='shipping_proof',content_sha256=contents*64)
    async def draft(self,case):
        return await self.j.reserve(case_id=case,owner_id='merchant-owner',operation_type='contest_draft')
    async def test_unresolved_upload_blocks_different_bytes(self):
        await self.upload('case1','a')
        with self.assertRaises(journal.OperationAlreadyExists):await self.upload('case1','b')
        self.assertEqual(len(store.rows),1)
    async def test_unresolved_upload_blocks_draft(self):
        await self.upload('case1','a')
        with self.assertRaises(journal.OperationAlreadyExists):await self.draft('case1')
    async def test_unresolved_draft_blocks_upload(self):
        await self.draft('case1')
        with self.assertRaises(journal.OperationAlreadyExists):await self.upload('case1','a')
    async def test_ambiguous_blocks_any_provider_op(self):
        op=await self.upload('case1','a')
        self.assertTrue(await self.j.transition(operation_id=op,owner_id='merchant-owner',state='ambiguous'))
        with self.assertRaises(journal.OperationAlreadyExists):await self.draft('case1')
    async def test_observed_blocks_other_operations(self):
        op=await self.upload('case1','a')
        self.assertTrue(await self.j.transition(operation_id=op,owner_id='merchant-owner',state='observed'))
        with self.assertRaises(journal.OperationAlreadyExists):await self.upload('case1','b')
    async def test_completed_allows_new_unique_operation(self):
        op=await self.upload('case1','a')
        self.assertTrue(await self.j.transition(operation_id=op,owner_id='merchant-owner',state='observed'))
        self.assertTrue(await self.j.transition(operation_id=op,owner_id='merchant-owner',state='completed'))
        await self.upload('case1','b')
        self.assertEqual(len(store.rows),2)
        with self.assertRaises(journal.OperationAlreadyExists):await self.upload('case1','a')
    async def test_different_cases_independent(self):
        await self.upload('case1','a');await self.upload('case2','b')
        self.assertEqual(len(store.rows),2)
    async def test_provider_stays_blocked_on_db_error(self):
        store.fail_commit=True
        with self.assertRaises(RuntimeError):await self.draft('case1')
    def test_pg_unique_partial_index_contract(self):
        index=next(i for i in model.RiskopsProviderOperation.__table__.indexes if i.name=='uq_riskops_one_pending_per_case')
        sql=str(CreateIndex(index).compile(dialect=postgresql.dialect()))
        self.assertIn('CREATE UNIQUE INDEX uq_riskops_one_pending_per_case',sql)
        self.assertIn('ON riskops_provider_operations (case_id)',sql)
        for state in ('reserved','observed','ambiguous'):self.assertIn(state,sql)
        self.assertNotIn("'completed'",sql)
    def test_conflict_policy_all_unique_constraints(self):
        import inspect
        text=inspect.getsource(journal.OperationJournal.reserve)
        self.assertIn('.on_conflict_do_nothing()',text)
        self.assertNotIn("index_elements=['operation_key']",text)
    def test_migration_has_conflict_precheck_and_no_automatic_downgrade(self):
        path=ROOT/'payload/migrations/versions/20261023_riskops_pending_gate_v8.py'
        source=path.read_text()
        self.assertIn('HAVING count(*) > 1',source)
        self.assertIn('raise RuntimeError',source)
        self.assertIn('20261023_riskops_ops_v7',source)
        self.assertIn('postgresql_where=sa.text(PENDING)',source)

if __name__=='__main__':unittest.main(verbosity=2)
