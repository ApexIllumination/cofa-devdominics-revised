// Local development only. Requires playwright and an installed browser.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const { chromium } = require("playwright");
async function main() {
  const base = new URL(process.argv[2]);
  assert(["localhost", "127.0.0.1", "[::1]"].includes(base.hostname), "Use a local test server.");
  const cfg = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
  const [a, b] = cfg.accounts;
  assert(a.id !== b.id && a.result !== b.result && a.result && b.result);
  const browser = await chromium.launch(process.env.CHROME_CHANNEL ? { channel: process.env.CHROME_CHANNEL } : {});
  try {
    const page = await browser.newPage();
    page.setDefaultTimeout(5000);
    const ui = key => page.getByTestId(cfg.testIds?.[key] ?? key);
    const visible = key => ui(key).waitFor({state:"visible"});
    async function exact(key, expected) {
      await visible(key);
      await page.waitForFunction(([id, value]) =>
        Array.from(document.querySelectorAll("[data-testid]")).some(el =>
          el.getAttribute("data-testid") === id && el.textContent.trim() === value),
        [cfg.testIds?.[key] ?? key, expected], {timeout:5000});
    }
    const url = path => new URL(path, base).href;
    const status = async (path, expected) => assert.equal((await page.request.get(url(path))).status(), expected);
    async function login(u) {
      await ui("id").fill(u.id); await ui("password").fill(u.password);
      await ui("login").click(); await exact("identity", u.id);
    }
    async function read(u) { await ui("read").click(); await exact("result", u.result); }
    await page.goto(base.href);
    await visible("login"); await status(cfg.resource,401);
    await login(a); await read(a); await read(a);
    console.log("PASS 로그인·보호 데이터·같은 버튼 연속 조회");

    // Hold the next GET until the visible loading state has been checked.
    let release, intercepted;
    const gate = new Promise(r => { release = r; });
    const seen = new Promise(r => { intercepted = r; });
    await page.route(url(cfg.resource), async route => {
      intercepted(); await gate;
      await route.fulfill({status:503, body:"test outage"});
    }, {times:1});
    const before = await ui("read").textContent();
    await ui("read").click();
    let timer;
    try {
      await Promise.race([seen, new Promise((_, reject) => { timer = setTimeout(() => reject(Error("No matching read request")), 5000); })]);
      assert(await ui("read").isDisabled(), "pending read button should be disabled");
    } finally { clearTimeout(timer); release(); }
    await exact("read", cfg.retryLabel);
    assert(await ui("read").isEnabled());
    assert(await ui("result").isHidden());
    await read(a);
    assert.equal(await ui("read").textContent(), before);
    console.log("PASS 조회 중 중복 조작 방지·503 표시·같은 버튼으로 복구");

    await page.reload(); await exact("identity", a.id); await read(a);
    await ui("logout").click(); await visible("login"); await status(cfg.resource,401);
    assert(!(await page.locator("body").innerText()).includes(a.result));
    await login(b);
    assert(!(await page.locator("body").innerText()).includes(a.result));
    await read(b);
    assert(!(await page.locator("body").innerText()).includes(a.result));
    console.log("PASS 새로고침 세션 유지·로그아웃 접근 차단·계정 전환 격리");

    // Invalidate the real session without telling the React tree; next read gets a real 401.
    assert.equal((await page.request.post(url(cfg.logout), { data:{} })).status(),204);
    await ui("read").click(); await visible("login");
    assert(!(await page.locator("body").innerText()).includes(b.result));
    console.log("PASS 사용 중 세션 무효화 → 로그인 복귀·이전 결과 제거");
  } finally { await browser.close(); }
}
main().catch(e => { console.error(e); process.exitCode = 1; });
