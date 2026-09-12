const wsUrl = process.argv[2];
const expression = process.argv[3];
if (!wsUrl || expression === undefined) {
  process.stderr.write("usage: cdp-eval.mjs <ws> <expression>\n");
  process.exit(2);
}
const ws = new WebSocket(wsUrl);
let ident = 0;
function send(payload) {
  ident += 1;
  ws.send(JSON.stringify({id: ident, ...payload}));
  return ident;
}
ws.addEventListener("open", () => {
  send({method: "Runtime.enable"});
  send({method: "Runtime.evaluate", params: {expression, awaitPromise: true, returnByValue: true}});
});
ws.addEventListener("message", (event) => {
  const message = JSON.parse(String(event.data));
  if (message.id !== 2) {
    return;
  }
  const result = message.result?.result;
  if (message.error || result?.subtype === "error") {
    process.stderr.write(JSON.stringify(message).slice(0, 800) + "\n");
    process.exit(1);
  }
  process.stdout.write(JSON.stringify(result?.value ?? null) + "\n");
  ws.close();
});
ws.addEventListener("error", (error) => {
  process.stderr.write(String(error) + "\n");
  process.exit(1);
});
