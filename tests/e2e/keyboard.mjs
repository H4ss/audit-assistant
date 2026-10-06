// E2E clavier dans un vrai navigateur (Chrome DevTools Protocol, WebSocket natif de Node >= 22).
// Usage : node keyboard.mjs <url_paladin> <port_cdp>   — code de sortie 1 en cas d'échec.
const [base, cdpPort] = process.argv.slice(2);
const targets = await (await fetch(`http://127.0.0.1:${cdpPort}/json/list`)).json();
const ws = new WebSocket(targets.find((t) => t.type === "page").webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener("open", r));
let id = 0;
const pending = new Map();
ws.addEventListener("message", (m) => {
  const d = JSON.parse(m.data);
  if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); }
});
const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const js = async (expr) => (await send("Runtime.evaluate", { expression: expr, returnByValue: true })).result.result.value;
const VK = { ArrowRight: 39, ArrowLeft: 37 };
const key = async (k) => {
  for (const type of ["keyDown", "keyUp"]) {
    await send("Input.dispatchKeyEvent", { type, key: k, code: k.length === 1 ? "Key" + k.toUpperCase() : k,
      text: type === "keyDown" && k.length === 1 ? k : undefined, windowsVirtualKeyCode: VK[k] || k.toUpperCase().charCodeAt(0) });
  }
};
const waitLoad = async (prev) => { for (let i = 0; i < 40; i++) { await sleep(150); const u = await js("location.href"); if (u !== prev && (await js("document.readyState")) === "complete") return; } };
const nav = async (url) => { await send("Page.navigate", { url }); await sleep(300); await waitLoad(""); };
const here = () => js("location.pathname");
const failures = [];
const check = (name, ok, got) => { console.log(`${ok ? "OK  " : "FAIL"} ${name}${ok ? "" : " — obtenu " + JSON.stringify(got)}`); if (!ok) failures.push(name); };

await send("Page.enable");
await nav(`${base}/c/demo/next?view=all`);
const first = await here();
await key("t"); check("T choisit True Positive", (await js("document.querySelector('input[name=verdict]:checked').value")) === "TRUE_POSITIVE");
await key("n"); check("N choisit Not an issue", (await js("document.querySelector('input[name=verdict]:checked').value")) === "NOT_AN_ISSUE");
await key("d"); check("D écrit la phrase exacte", (await js("document.getElementById('comment').value")) === "security appetite to be discussed");
await js("document.getElementById('comment').value = 'texte libre'");
await key("d"); check("D ne remplace pas un texte libre", (await js("document.getElementById('comment').value")) === "texte libre");
await key("d"); check("D (2e appui) remplace", (await js("document.getElementById('comment').value")) === "security appetite to be discussed");
await js("document.querySelector('input[name=verdict][value=NOT_AN_ISSUE]').focus()");
await key("ArrowRight"); await sleep(500);
check("→ sur un radio ne passe pas le finding", (await here()) === first, await here());
await js("document.activeElement.blur(); document.querySelector('input[name=verdict][value=NOT_AN_ISSUE]').checked = true");
let before = await js("location.href");
await key("a"); await waitLoad(before);
check("A valide et passe au suivant", (await here()) !== first, await here());
check("Décision confirmée à l'écran", ((await js("(document.querySelector('.flash')||{}).textContent||''")).includes("Décision enregistrée")));
before = await js("location.href");
await key("u"); await waitLoad(before);
check("U annule et revient sur le finding", (await here()) === first, await here());
await js("const c = document.getElementById('comment'); c.value = 'brouillon e2e'; c.dispatchEvent(new Event('input'))");
before = await js("location.href");
await js("document.getElementById('nav-next').click()"); await waitLoad(before);
await nav(base + first);
check("Brouillon restauré après navigation", (await js("document.getElementById('comment').value")) === "brouillon e2e");
ws.close();
process.exit(failures.length ? 1 : 0);
