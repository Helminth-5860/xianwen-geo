import chunk0 from "./logo-data-0";
import chunk1 from "./logo-data-1";
import chunk2 from "./logo-data-2";
import chunk3 from "./logo-data-3";
import chunk4 from "./logo-data-4";
import chunk5 from "./logo-data-5";

const encoded = `${chunk0}${chunk1}${chunk2}${chunk3}${chunk4}${chunk5}`.replace(/\s+/g, "");

export const officialXianwenLogoDataUrl = `data:image/webp;base64,${encoded}`;
