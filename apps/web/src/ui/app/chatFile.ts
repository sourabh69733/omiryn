// The text of a WhatsApp export the person picked: the .txt itself (Android), or the chat's .txt
// from inside the .zip an iPhone makes. Read in the browser; a long chat keeps its newest part.

// The API's limit (about months of a busy chat).
export const MAX_CHAT_CHARS = 1_000_000;
export const CHAT_FILE_ACCEPT = ".txt,.zip,text/plain,application/zip";

const END_OF_DIRECTORY = 0x06054b50;
const DIRECTORY_ENTRY = 0x02014b50;
const LOCAL_ENTRY = 0x04034b50;
// The end record is 22 bytes plus a comment of at most 65,535.
const TAIL_BYTES = 22 + 65_535;

export function isZip(file: { name: string; type?: string }): boolean {
  return /\.zip$/i.test(file.name) || /zip/i.test(file.type || "");
}

export async function chatFileText(file: File): Promise<string> {
  const text = isZip(file) ? await zippedChatText(file) : await file.text();
  return text.slice(-MAX_CHAT_CHARS);
}

type Entry = { name: string; method: number; packed: number; at: number };

/** The chat's text from an export .zip. Only the list of files and the one .txt are read, so a
    zip full of photos is as quick as one without. */
export async function zippedChatText(file: Blob): Promise<string> {
  const chat = pickChat(await zipEntries(file));
  if (!chat) throw new Error("There is no chat in that zip. Export the chat from WhatsApp and pick that file.");
  const head = new DataView(await file.slice(chat.at, chat.at + 30).arrayBuffer());
  if (head.byteLength < 30 || head.getUint32(0, true) !== LOCAL_ENTRY) throw new Error("Couldn't open that zip. Export the chat again.");
  const start = chat.at + 30 + head.getUint16(26, true) + head.getUint16(28, true);
  const packed = file.slice(start, start + chat.packed);
  if (chat.method === 0) return packed.text();
  if (chat.method !== 8 || typeof DecompressionStream === "undefined") {
    throw new Error("This browser can't open that zip. Unzip it and pick the .txt file inside.");
  }
  return new Response(packed.stream().pipeThrough(new DecompressionStream("deflate-raw"))).text();
}

async function zipEntries(file: Blob): Promise<Entry[]> {
  const tailAt = Math.max(0, file.size - TAIL_BYTES);
  const tail = new DataView(await file.slice(tailAt).arrayBuffer());
  let end = -1;
  for (let i = tail.byteLength - 22; i >= 0; i -= 1) {
    if (tail.getUint32(i, true) === END_OF_DIRECTORY) { end = i; break; }
  }
  if (end < 0) throw new Error("That file isn't a zip WhatsApp made. Export the chat again.");
  const size = tail.getUint32(end + 12, true);
  const at = tail.getUint32(end + 16, true);
  const directory = new DataView(await file.slice(at, at + size).arrayBuffer());
  const decoder = new TextDecoder();
  const entries: Entry[] = [];
  let offset = 0;
  while (offset + 46 <= directory.byteLength && directory.getUint32(offset, true) === DIRECTORY_ENTRY) {
    const nameLength = directory.getUint16(offset + 28, true);
    const name = decoder.decode(new Uint8Array(directory.buffer, directory.byteOffset + offset + 46, nameLength));
    entries.push({ name, method: directory.getUint16(offset + 10, true), packed: directory.getUint32(offset + 20, true), at: directory.getUint32(offset + 42, true) });
    offset += 46 + nameLength + directory.getUint16(offset + 30, true) + directory.getUint16(offset + 32, true);
  }
  return entries;
}

// "_chat.txt" on iPhone, "WhatsApp Chat with Riya.txt" on Android; never a Mac's hidden copy.
function pickChat(entries: Entry[]): Entry | null {
  const texts = entries.filter((entry) => /\.txt$/i.test(entry.name) && !entry.name.startsWith("__MACOSX/") && !/(^|\/)\./.test(entry.name));
  return texts.find((entry) => /(^|\/)_chat\.txt$/i.test(entry.name)) || texts.find((entry) => /whatsapp/i.test(entry.name)) || texts[0] || null;
}
