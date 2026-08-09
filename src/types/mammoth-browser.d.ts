declare module "mammoth/mammoth.browser" {
  interface MammothMessage {
    message: string;
    type: string;
  }

  interface RawTextResult {
    value: string;
    messages: MammothMessage[];
  }

  export function extractRawText(input: { arrayBuffer: ArrayBuffer }): Promise<RawTextResult>;
}
