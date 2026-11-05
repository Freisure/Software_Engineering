"use strict";
const $ = (s, root = document) => root.querySelector(s);
const esc = (v) =>
  String(v ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const states = {
  pending: "待确认",
  approved: "审核通过",
  rejected: "已驳回",
  withdrawn: "已下架",
  accepted: "已预约",
  ready: "待交接",
  confirming: "待双方确认",
  completed: "已完成",
  cancelled: "已取消",
  disputed: "待处理",
  no_show: "爽约",
  upheld: "成立",
  dismissed: "不成立",
  overturned: "处罚已撤销",
};
const conditions = {
  5: "全新 / 近全新",
  4: "九成新",
  3: "八成新",
  2: "七成新",
  1: "有明显使用痕迹",
};
let user = null,
  csrf = "",
  courses = [],
  demo = false,
  adminTab = "overview",
  routeVersion = 0;
let toastTimer;
function toast(message) {
  $("#toast").textContent = message;
  $("#toast").classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => $("#toast").classList.remove("show"), 4000);
}
async function api(path, method = "GET", body) {
  const options = { method, headers: { "X-CSRF-Token": csrf } };
  if (body instanceof FormData) options.body = body;
  else if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const r = await fetch("/api" + path, options);
  const value = await r.json();
  if (!r.ok) throw Error(value.error || "操作未完成，请重试");
  return value;
}
async function refreshMe() {
  const me = await api("/me");
  user = me.user;
  csrf = me.csrf_token || "";
  demo = me.demo;
  navigation();
}
const badge = (s, label) =>
  `<span class="badge ${esc(s)}">${esc(label || states[s] || s)}</span>`;
const price = (p) =>
  p === 0
    ? '<span class="price free">免费赠送</span>'
    : `<span class="price"><small>¥</small> ${(p / 100).toFixed(2)}</span>`;
const empty = (title, detail) =>
  `<div class="empty"><strong>${esc(title)}</strong>${esc(detail)}</div>`;
const field = (name, label, type = "text", value = "", extra = "") =>
  `<div class="field"><label for="f-${esc(name)}">${label}</label><input id="f-${esc(name)}" name="${esc(name)}" type="${type}" value="${esc(value)}" ${extra}></div>`;
const textarea = (name, label, value = "", extra = "") =>
  `<div class="field"><label for="f-${name}">${label}</label><textarea id="f-${name}" name="${name}" ${extra}>${esc(value)}</textarea></div>`;
const select = (name, label, options, value = "") =>
  `<div class="field"><label for="f-${name}">${label}</label><select id="f-${name}" name="${name}">${options.map(([v, t]) => `<option value="${esc(v)}" ${String(value) === String(v) ? "selected" : ""}>${esc(t)}</option>`).join("")}</select></div>`;
const values = (f) => Object.fromEntries(new FormData(f));
function formHandler(id, handler) {
  const f = $(id);
  f.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = f.querySelector("[type=submit]");
    const error = f.querySelector(".error");
    if (error) error.textContent = "";
    if (button) button.disabled = true;
    try {
      await handler(values(f), f);
    } catch (e) {
      if (error) {
        error.textContent = e.message;
        error.focus();
      } else toast(e.message);
    } finally {
      if (button) button.disabled = false;
    }
  });
}
function modal(title, html) {
  $("#modal-title").textContent = title;
  $("#modal-body").innerHTML = html;
  if (!$("#modal").open) $("#modal").showModal();
}
const closeModal = () => $("#modal").close();
$("#close-modal").addEventListener("click", closeModal);
$(".skip").addEventListener("click", (event) => {
  event.preventDefault();
  $("#main").focus();
});
function navigation() {
  const route = location.hash.slice(1) || "market";
  const links = [
    ["market", "教材集市"],
    ["publish", "发布教材"],
    ["mine", "我的书架"],
    ["reservations", "我的预约"],
  ];
  if (user?.role === "admin") links.push(["admin", "管理中心"]);
  $("#nav").innerHTML = links
    .map(
      ([r, t]) =>
        `<a href="#${r}" class="${r === route ? "active" : ""}" ${r === route ? 'aria-current="page"' : ""}>${t}</a>`,
    )
    .join("");
  $("#account").innerHTML = user
    ? `<a href="#profile">${esc(user.nickname)}</a><button class="quiet small" data-action="logout">退出</button>`
    : '<a href="#login">登录 / 注册</a>';
}
const head = (title, sub, action = "") =>
  `<div class="section-head"><div><h2>${title}</h2><p>${sub}</p></div>${action}</div>`;
function bookCard(b, mode = "market") {
  return `<article class="book"><div class="cover"><img src="${esc(b.images[0])}" alt="${esc(b.title)}封面" loading="lazy">${badge(b.status, mode === "market" ? conditions[b.condition] : b.status === "pending" ? "待审核" : states[b.status])}</div><div class="book-body"><span class="course-code">${esc(b.course_code)} · ${esc(b.course_name)}</span><h3>${esc(b.title)}</h3><span class="meta">${esc(b.edition || "未标注版次")} / ${esc(b.college)}</span><div class="price-row">${price(b.price)}<span class="meta">${esc(b.nickname)} · 信用 ${b.credit}</span></div>${b.review_reason ? `<p class="hint">审核说明：${esc(b.review_reason)}</p>` : ""}<div class="actions">${mode === "mine" ? `<button class="secondary small" data-action="edit" data-id="${b.id}">编辑重提</button>${b.status !== "completed" && b.status !== "withdrawn" ? `<button class="quiet small" data-action="withdraw" data-id="${b.id}">下架</button>` : ""}` : mode === "moderation" ? `<button class="small" data-action="review" data-id="${b.id}">审核信息</button>` : `<button class="secondary small" data-action="detail" data-id="${b.id}">查看教材</button>`}</div></div></article>`;
}
async function market() {
  const colleges = [...new Set(courses.map((c) => c.college))];
  $("#main").innerHTML =
    `<section class="hero"><div class="hero-copy"><span class="eyebrow">同一门课，让好书再次相遇</span><h1>上一届的笔记，<br><em>下一程的起点。</em></h1><p>输入课程代码，找到正好需要的教材。与同校同学约个时间，让闲置的书继续发光。</p><div class="actions"><button data-action="focus-search">按课程找书</button><button class="secondary" data-action="go-publish">发布我的教材</button></div></div><div class="hero-art" aria-hidden="true"><div class="spine">软件工程</div><div class="spine">数据结构</div><div class="spine">高等数学</div><small>每一本教材，都值得被继续翻阅</small></div></section>${head("发现你的下一本教材", "按课程匹配，线下安心交接。")}<div class="catalog-layout"><form id="filters" class="filters"><h3>筛选教材</h3>${select("college", "所属学院", [["", "全部学院"], ...colleges.map((c) => [c, c])])}${select("course", "课程", [["", "全部课程"], ...courses.map((c) => [c.code, c.code + " " + c.name])])}${select("condition", "最低成色", [["", "不限成色"], ...Object.entries(conditions).reverse()])}<div class="form-grid">${field("min_price", "最低价", "number", "", 'min="0" step="0.01"')}${field("max_price", "最高价", "number", "", 'min="0" step="0.01"')}</div><label class="check"><input name="free" type="checkbox" value="1">只看免费赠送</label><div class="actions"><button type="submit" class="small">应用筛选</button><button type="reset" class="quiet small">重置</button></div><p class="hint">仅展示审核通过且可预约的教材。</p></form><section><form id="search" class="searchbar"><input name="q" id="query" aria-label="搜索课程代码或教材" placeholder="输入课程代码、课程名或教材名，如 SE301"><button type="submit">搜索</button><select name="sort" aria-label="排序"><option value="newest">最新发布</option><option value="price">价格从低到高</option><option value="condition">成色优先</option></select></form><div id="recommendation"></div><p id="result-count" class="results-note" aria-live="polite"></p><div id="book-grid" class="grid"></div></section></div>`;
  let searchVersion = 0;
  async function search() {
    const ticket = ++searchVersion;
    const p = new URLSearchParams({
      ...values($("#filters")),
      ...values($("#search")),
    });
    const books = await api("/books?" + p);
    if (ticket !== searchVersion || !$("#book-grid")) return;
    $("#result-count").textContent = `找到 ${books.length} 本可预约教材`;
    $("#book-grid").innerHTML = books.length
      ? books.map((b) => bookCard(b)).join("")
      : empty("暂时没有匹配的教材", "试试缩短课程代码，或放宽筛选条件。");
    const query = $("#query").value.trim().toUpperCase();
    const matched = courses.filter((c) => query && c.code.includes(query));
    $("#recommendation").innerHTML = matched.length
      ? `<div class="notice">课程常用教材：${matched.map((c) => `${esc(c.code)} ${esc(c.textbook || c.name)}`).join("；")}</div>`
      : "";
  }
  formHandler("#search", search);
  formHandler("#filters", search);
  $("#search select").addEventListener("change", () =>
    search().catch((e) => toast(e.message)),
  );
  $("#filters").addEventListener("reset", () =>
    setTimeout(() => search().catch((e) => toast(e.message)), 0),
  );
  await search();
}
function loginPage(register = false) {
  $("#main").innerHTML =
    `<div class="auth-box"><div class="panel"><span class="eyebrow">欢迎来到书循环</span><h1>${register ? "创建校园账号" : "让好书，再流转一次"}</h1><p class="hint">${register ? "账号仅用于本校教材流转，不需要身份证信息。" : "使用学号登录，管理你的教材与交接。"}</p><form id="auth-form">${field("student_id", "学号", "text", "", 'required minlength="4" maxlength="24" autocomplete="username"')}${register ? field("nickname", "昵称", "text", "", 'required maxlength="30"') + field("college", "学院", "text", "", 'required maxlength="50"') + field("class_name", "班级", "text", "", 'required maxlength="50"') : ""}${field("password", "密码", "password", "", 'required minlength="8" maxlength="128" autocomplete="' + (register ? "new-password" : "current-password") + '"')}<p class="error" tabindex="-1" role="alert"></p><button type="submit">${register ? "注册账号" : "登录"}</button></form><p class="hint">${register ? '已有账号？ <a href="#login">返回登录</a>' : '还没有账号？ <a href="#register">注册账号</a>'}</p></div>${demo ? '<div class="notice">演示账号：20240001（发布者）、20240002（需求者）、admin（管理员）<br>演示密码均为 Campus2026!<br>演示数据均为虚构。</div>' : ""}</div>`;
  formHandler("#auth-form", async (d) => {
    await api(register ? "/register" : "/login", "POST", d);
    if (register) {
      toast("注册成功，请登录");
      location.hash = "login";
    } else {
      await refreshMe();
      location.hash = "market";
      toast("登录成功");
    }
  });
}
async function publishPage(id) {
  let b = id ? await api("/books/" + id) : null;
  $("#main").innerHTML =
    `<div class="narrow">${head(b ? "编辑并重新送审" : "发布一本教材", "填写教材信息，审核通过后即可被同课程同学找到。")}<div class="notice">请勿在封面、标题和备注中公开联系方式。联系方式可在个人资料设置，仅预约确认后向对方展示。</div><form id="publish-form" class="panel"><div class="form-grid">${select(
      "course_code",
      "关联课程 *",
      courses.map((c) => [c.code, c.code + " " + c.name]),
      b?.course_code,
    )}${field("title", "教材名称 *", "text", b?.title, 'required maxlength="100"')}${field("edition", "版次", "text", b?.edition, 'maxlength="50"')}${field("isbn", "ISBN（选填）", "text", b?.isbn, 'maxlength="30"')}${select("condition", "成色 *", Object.entries(conditions).reverse(), b?.condition || 4)}${field("price", "价格 / 元（0 表示免费）*", "number", b ? b.price / 100 : "", 'required min="0" max="10000" step="0.01"')}</div>${textarea("notes", "教材描述", b?.notes, 'maxlength="1000" placeholder="例如：书页完整，第3章有少量笔记，可在图书馆交接"')}<div class="field"><label for="book-images">教材图片 *（1—3张）</label><input id="book-images" type="file" accept="image/jpeg,image/png,image/webp" multiple><p class="hint">支持 JPG、PNG、WebP，每张不超过 5MB。${b ? "不选择新图片则保留原图片；选择后替换全部原图。" : ""}</p><div class="preview" id="preview">${(b?.images || []).map((src) => `<img src="${esc(src)}" alt="原教材图片">`).join("")}</div></div><p class="error" tabindex="-1" role="alert"></p><div class="actions"><button type="submit">提交审核</button><a href="#mine">返回我的书架</a></div></form></div>`;
  let previewUrls = [];
  $("#book-images").addEventListener("change", () => {
    previewUrls.forEach(URL.revokeObjectURL);
    previewUrls = Array.from($("#book-images").files)
      .slice(0, 3)
      .map((f) => URL.createObjectURL(f));
    $("#preview").innerHTML = previewUrls
      .map((src) => `<img src="${src}" alt="待上传教材预览">`)
      .join("");
  });
  formHandler("#publish-form", async (d) => {
    let images = b?.images || [];
    const files = Array.from($("#book-images").files);
    if (files.length > 3) throw Error("最多上传3张图片");
    if (files.some((f) => f.size > 5 * 1024 * 1024))
      throw Error("每张图片最多5MB");
    if (files.length) {
      images = [];
      for (const f of files) {
        const fd = new FormData();
        fd.append("file", f);
        images.push((await api("/uploads", "POST", fd)).url);
      }
    }
    if (!images.length) throw Error("请上传至少1张教材图片");
    await api(id ? "/books/" + id : "/books", id ? "PUT" : "POST", {
      ...d,
      condition: +d.condition,
      images,
    });
    previewUrls.forEach(URL.revokeObjectURL);
    toast("已提交审核");
    location.hash = "mine";
  });
}
async function detail(id) {
  const b = await api("/books/" + id);
  modal(
    "教材详情",
    `<div class="detail"><img src="${esc(b.images[0])}" alt="${esc(b.title)}封面"><div><span class="course-code">${esc(b.course_code)} · ${esc(b.course_name)}</span><h3>${esc(b.title)}</h3>${price(b.price)}<p>${esc(b.edition)} / ${esc(conditions[b.condition])}<br>${esc(b.college)}<br>${esc(b.nickname)} · 信用 ${b.credit}</p></div></div><div class="preview">${b.images
      .slice(1)
      .map((src) => `<img src="${esc(src)}" alt="教材补充图片">`)
      .join(
        "",
      )}</div><p>${esc(b.notes || "发布者暂未补充描述")}</p><p class="hint">ISBN：${esc(b.isbn || "未填写")}<br>课程常用教材：${esc(b.textbook || "未维护")}</p><div class="actions">${b.owner_id !== user?.id && b.status === "approved" ? `<button data-action="reserve" data-id="${id}">预约这本教材</button>` : ""}<button class="quiet" data-action="report" data-id="${id}">举报 / 申诉</button></div>${b.ratings.length ? "<h3>发布者收到的评价</h3>" + b.ratings.map((r) => `<p class="hint">${esc(r.nickname)}：准时 ${r.punctuality}/5 · 描述 ${r.accuracy}/5 · 沟通 ${r.communication}/5<br>${esc(r.tags)} ${esc(r.comment)}</p>`).join("") : ""}`,
  );
}
function requireLogin() {
  if (user) return true;
  closeModal();
  location.hash = "login";
  toast("请先登录");
  return false;
}
function reserveDialog(id) {
  if (!requireLogin()) return;
  modal(
    "预约线下交接",
    `<p class="hint">选择北京时间与校内公共场所。发布者接受后，你们可以看到彼此的联系方式。</p><form id="reserve-form">${field("meeting_time", "期望交接时间（北京时间）", "datetime-local", "", "required")}${field("place", "交接地点", "text", "", 'required maxlength="100" placeholder="例如：图书馆一楼服务台旁"')}${textarea("message", "给发布者留言", "", 'maxlength="500"')}<p class="error" tabindex="-1" role="alert"></p><button type="submit">发起预约</button></form>`,
  );
  formHandler("#reserve-form", async (d) => {
    await api("/books/" + id + "/reservations", "POST", d);
    closeModal();
    toast("预约已发送，等待发布者确认");
    location.hash = "reservations";
  });
}
async function mine() {
  const books = await api("/books?mine=1");
  $("#main").innerHTML =
    head(
      "我的书架",
      "查看审核进度，管理发布的教材。",
      '<button data-action="go-publish">发布教材</button>',
    ) +
    (books.length
      ? `<div class="grid">${books.map((b) => bookCard(b, "mine")).join("")}</div>`
      : empty("书架还是空的", "点击“发布教材”，让你的闲置教材流转起来。"));
}
function rsvActions(r, admin = false) {
  if (admin)
    return `<button data-action="resolve-rsv" data-id="${r.id}" data-owner="${r.owner_id}" data-buyer="${r.buyer_id}">处理申诉</button>`;
  let html = "";
  const seller = r.owner_id === user.id;
  const btn = (act, label, cls = "secondary") =>
    `<button class="${cls} small" data-action="rsv" data-id="${r.id}" data-op="${act}">${label}</button>`;
  if (r.status === "pending" && seller)
    html += btn("accept", "接受预约", "") + btn("reject", "拒绝预约");
  if (["pending", "accepted"].includes(r.status))
    html += btn("cancel", "取消预约");
  if (r.status === "accepted") html += btn("ready", "开始交接", "");
  if (
    ["ready", "confirming"].includes(r.status) &&
    !(seller ? r.seller_confirm : r.buyer_confirm)
  )
    html += btn("confirm", "确认已交接", "");
  if (["accepted", "ready", "confirming"].includes(r.status))
    html += btn("appeal", "申诉 / 爽约");
  if (r.status === "completed" && !r.rated)
    html += `<button class="small" data-action="rate" data-id="${r.id}">评价对方</button>`;
  if (["completed", "no_show"].includes(r.status))
    html += `<button class="quiet small" data-action="report" data-id="${r.book_id}">对结果申诉</button>`;
  return html;
}
function rsvCard(r, admin = false) {
  return `<article class="record"><div class="record-head"><div><span class="course-code">预约 #${r.id} · ${admin ? "交接申诉" : r.owner_id === user.id ? "我发布的教材" : "我需要的教材"}</span><h3>${esc(r.title)}</h3></div>${badge(r.status)}</div><div class="timeline">${["pending", "accepted", "ready", "confirming", "completed"].map((s) => `<span class="${r.status === s ? "current" : ""}">${states[s]}</span>`).join("")}</div><p>交接时间：${esc(r.meeting_time.replace("T", " "))}（北京时间）<br>交接地点：${esc(r.place)}<br>对方：${esc(r.other_name)}${r.contact ? "<br>联系方式：" + esc(r.contact) : ""}${r.message ? "<br>留言：" + esc(r.message) : ""}${r.reason ? "<br>处理说明：" + esc(r.reason) : ""}</p>${r.status === "confirming" ? `<p class="notice">${r.seller_confirm ? "发布者已确认" : "发布者待确认"} / ${r.buyer_confirm ? "需求者已确认" : "需求者待确认"}。超时后进入管理员处理队列。</p>` : ""}<div class="actions">${rsvActions(r, admin)}</div></article>`;
}
async function reservations() {
  const list = await api("/reservations");
  $("#main").innerHTML =
    head("我的预约", "确认时间地点，完成线下交接，再给彼此一份评价。") +
    (list.length
      ? list.map((r) => rsvCard(r)).join("")
      : empty(
          "还没有预约记录",
          "到教材集市找到你需要的教材，发起第一次预约。",
        ));
}
function reasonDialog(title, callback) {
  modal(
    title,
    `<form id="reason-form">${textarea("reason", "请说明原因", "", 'required maxlength="500"')}<p class="error" tabindex="-1" role="alert"></p><button type="submit">确认提交</button></form>`,
  );
  formHandler("#reason-form", async (d) => {
    await callback(d.reason);
    closeModal();
    toast("操作已保存");
    await render();
  });
}
async function rsvAction(id, action) {
  const execute = async (reason) => {
    await api("/reservations/" + id + "/action", "POST", { action, reason });
    await refreshMe();
  };
  if (["reject", "cancel", "appeal"].includes(action)) {
    reasonDialog(
      { reject: "拒绝预约", cancel: "取消预约", appeal: "提交交接申诉" }[
        action
      ],
      execute,
    );
  } else if (action === "confirm") {
    modal(
      "确认已完成线下交接",
      `<p>请确认你已当面交付或收到教材。双方确认后，预约将完成并结算信用分。</p><button data-action="confirm-handoff" data-id="${id}">我已完成交接</button>`,
    );
  } else {
    await execute("");
    toast("预约状态已更新");
    await render();
  }
}
function ratingDialog(id) {
  modal(
    "评价这次交接",
    `<form id="rating-form"><div class="form-grid">${[
      "punctuality",
      "accuracy",
      "communication",
    ]
      .map((k, i) =>
        select(
          k,
          ["准时程度", "描述一致", "沟通体验"][i],
          [5, 4, 3, 2, 1].map((v) => [v, v + " 星"]),
          5,
        ),
      )
      .join(
        "",
      )}</div>${field("tags", "标签（选填）", "text", "", 'maxlength="100" placeholder="准时、书况好、沟通顺畅"')}${textarea("comment", "评价内容", "", 'maxlength="500"')}<p class="error" tabindex="-1" role="alert"></p><button type="submit">提交评价</button></form>`,
  );
  formHandler("#rating-form", async (d) => {
    await api("/reservations/" + id + "/rating", "POST", d);
    closeModal();
    toast("评价已提交");
    await render();
  });
}
function reportDialog(id) {
  if (!requireLogin()) return;
  reasonDialog("举报或申诉", async (reason) => {
    await api("/reports", "POST", { book_id: +id, reason });
    toast("已提交管理员处理");
  });
}
async function profile() {
  const [notes, reports, ratings] = await Promise.all([
    api("/notifications"),
    api("/reports"),
    api("/ratings"),
  ]);
  $("#main").innerHTML =
    head("个人中心", "维护资料，查看消息、信用与申诉进度。") +
    `<div class="panel profile-head"><div class="avatar">${esc(user.nickname.slice(0, 1))}</div><div><h3>${esc(user.nickname)}</h3><span class="meta">${esc(user.student_id)} / ${esc(user.college)} / ${esc(user.class_name)}</span></div><div class="price">${user.credit}<small> 信用分</small></div></div><div class="split"><form id="profile-form" class="panel"><h3>个人资料</h3>${field("nickname", "昵称", "text", user.nickname, 'required maxlength="30"')}${field("college", "学院", "text", user.college, 'required maxlength="50"')}${field("class_name", "班级", "text", user.class_name, 'required maxlength="50"')}${field("contact", "联系方式", "text", user.contact, 'maxlength="100"')}<p class="hint">仅预约接受后对交易对方可见。累计主动取消 ${user.cancellations} 次。</p><p class="error" role="alert" tabindex="-1"></p><button type="submit">保存资料</button></form><div><form id="password-form" class="panel"><h3>修改密码</h3>${field("old_password", "原密码", "password", "", 'required autocomplete="current-password"')}${field("password", "新密码", "password", "", 'required minlength="8" maxlength="128" autocomplete="new-password"')}<p class="error" role="alert" tabindex="-1"></p><button type="submit" class="secondary">更新密码</button></form><div class="panel"><div class="section-head"><h3>站内消息</h3><button class="quiet small" data-action="read-notes">全部已读</button></div>${
      notes.length
        ? notes
            .slice(0, 10)
            .map(
              (n) =>
                `<p class="hint">${n.seen ? "" : "● "}${esc(n.message)}<br>${esc(n.created_at)} UTC</p>`,
            )
            .join("")
        : '<p class="hint">暂无新消息。</p>'
    }</div></div></div><div class="panel"><h3>举报与申诉</h3>${reports.length ? reports.map((r) => reportCard(r, false)).join("") : '<p class="hint">暂无举报或申诉记录。你可以从教材详情或已完成预约发起。</p>'}</div><div class="panel"><h3>我的评价</h3>${ratings.length ? ratings.map((r) => `<div class="record"><p>预约 #${r.reservation_id} · ${r.author_id === user.id ? "我发出的" : "我收到的"}评价<br>准时 ${r.punctuality}/5 · 描述 ${r.accuracy}/5 · 沟通 ${r.communication}/5<br>${esc(r.tags)} ${esc(r.comment)}</p>${r.author_id === user.id ? `<button class="quiet small" data-action="delete-rating" data-id="${r.id}">删除评价</button>` : '<p class="hint">如有异议，请在对应预约中点击“对结果申诉”。</p>'}</div>`).join("") : '<p class="hint">完成交接后即可互评。</p>'}</div>`;
  formHandler("#profile-form", async (d) => {
    await api("/profile", "PUT", d);
    await refreshMe();
    toast("资料已保存");
  });
  formHandler("#password-form", async (d, f) => {
    await api("/password", "POST", d);
    f.reset();
    toast("密码已更新，其他设备需重新登录");
  });
}
function reportCard(r, admin) {
  return `<div class="record"><div class="record-head"><h3>#${r.id} ${esc(r.title)}</h3>${badge(r.status, r.status === "pending" ? "待处理" : undefined)}</div><p>${esc(r.reason)}</p>${r.resolution ? `<p>处理结果：${esc(r.resolution)}</p>` : ""}${r.status === "pending" ? (admin ? `<button class="small" data-action="resolve-report" data-id="${r.id}">处理举报 / 申诉</button>` : r.author_id === user.id ? `<button class="quiet small" data-action="retract-report" data-id="${r.id}">撤回举报</button>` : "") : ""}${!admin && r.status === "upheld" && r.owner_id === user.id && !r.original_id ? `<button class="quiet small" data-action="appeal-report" data-id="${r.id}">申请撤销处罚</button>` : ""}</div>`;
}
async function admin() {
  if (user.role !== "admin") throw Error("仅管理员可访问管理中心");
  $("#main").innerHTML =
    head("管理中心", "让教材信息可信，让每次交接有迹可循。") +
    `<div class="tabs">${[
      ["overview", "统计概览"],
      ["moderation", "教材审核"],
      ["disputes", "交接申诉"],
      ["reports", "举报处理"],
      ["courses", "课程库"],
      ["settings", "规则设置"],
      ["logs", "操作日志"],
    ]
      .map(
        ([k, t]) =>
          `<button class="${adminTab === k ? "active" : ""}" data-action="admin-tab" data-tab="${k}">${t}</button>`,
      )
      .join(
        "",
      )}</div><div id="admin-content"><p class="loading">正在加载…</p></div>`;
  await adminContent();
}
async function adminContent() {
  const box = $("#admin-content");
  if (adminTab === "overview") {
    box.innerHTML = `<form id="stats-filter" class="row-filter">${select("college", "学院", [["", "全部学院"], ...[...new Set(courses.map((c) => c.college))].map((c) => [c, c])])}${field("start", "发布起始日期", "date")}${field("end", "发布截止日期", "date")}<div class="actions"><button type="submit">查询</button><a id="export" href="/api/admin/export">导出 CSV</a></div></form><div id="stats-result"></div>`;
    async function load() {
      const q = new URLSearchParams(values($("#stats-filter")));
      const s = await api("/admin/stats?" + q);
      $("#export").href = "/api/admin/export?" + q;
      $("#stats-result").innerHTML = `<div class="stats">${[
        ["发布教材", s.published],
        ["审核通过率", s.approval_rate + "%"],
        ["成功交接", s.completed],
        ["已处理举报", s.handled_reports + "/" + s.reports],
      ]
        .map(
          ([k, v]) =>
            `<div class="stat"><span>${k}</span><strong>${v}</strong></div>`,
        )
        .join(
          "",
        )}</div><div class="panel"><h3>热门课程 · 按教材发布数</h3>${s.hot_courses.length ? s.hot_courses.map((c) => `<div class="bar-row"><span>${esc(c.code)} ${esc(c.name)}</span><progress value="${c.count}" max="${s.hot_courses[0].count}" aria-label="${esc(c.name)}发布数">${c.count}</progress><strong>${c.count}</strong></div>`).join("") : "暂无数据"}<p class="hint">按教材发布日期与当前课程学院筛选；通过率按当前已通过、已完成、已驳回记录计算。</p></div>`;
    }
    formHandler("#stats-filter", load);
    await load();
  } else if (adminTab === "moderation") {
    const list = await api("/books?moderation=1");
    box.innerHTML = list.length
      ? `<div class="grid">${list.map((b) => bookCard(b, "moderation")).join("")}</div>`
      : empty("待审核队列已清空", "新发布和编辑重提的教材会出现在这里。");
  } else if (adminTab === "disputes") {
    const list = await api("/reservations?disputes=1");
    box.innerHTML = list.length
      ? list.map((r) => rsvCard(r, true)).join("")
      : empty("暂无待处理交接", "超时确认和主动申诉会进入此队列。");
  } else if (adminTab === "reports") {
    const list = await api("/reports");
    box.innerHTML = list.length
      ? list.map((r) => reportCard(r, true)).join("")
      : empty("暂无举报", "举报与申诉将显示在这里。");
  } else if (adminTab === "courses") {
    box.innerHTML = `<div class="split"><form id="course-form" class="panel"><h3>新增 / 更新课程</h3>${field("code", "课程代码", "text", "", 'required maxlength="30"')}${field("name", "课程名称", "text", "", 'required maxlength="100"')}${field("college", "所属学院", "text", "", 'required maxlength="50"')}${field("textbook", "常用教材及版次", "text", "", 'maxlength="200"')}<p class="hint">填写已有代码会更新该课程。</p><p class="error" role="alert" tabindex="-1"></p><button type="submit">保存课程</button></form><form id="import-form" class="panel"><h3>批量导入 CSV</h3><div class="field"><label for="csv-file">选择 UTF-8 CSV 文件</label><input id="csv-file" type="file" accept=".csv,text/csv"></div>${textarea("csv", "或粘贴 CSV 内容", "code,name,college,textbook\nSE302,软件测试,计算机学院,软件测试技术", "required")}<p class="error" role="alert" tabindex="-1"></p><button type="submit" class="secondary">导入课程</button></form></div><div class="panel table-wrap"><table><thead><tr><th>代码</th><th>课程</th><th>学院</th><th>常用教材</th></tr></thead><tbody>${courses.map((c) => `<tr><td>${esc(c.code)}</td><td>${esc(c.name)}</td><td>${esc(c.college)}</td><td>${esc(c.textbook)}</td></tr>`).join("")}</tbody></table></div>`;
    $("#csv-file").addEventListener("change", async (e) => {
      const f = e.target.files[0];
      if (f) $("#f-csv").value = await f.text();
    });
    formHandler("#course-form", async (d) => {
      await api("/admin/courses", "POST", d);
      courses = await api("/courses");
      toast("课程已保存");
      await adminContent();
    });
    formHandler("#import-form", async (d) => {
      const r = await api("/admin/courses/import", "POST", d);
      courses = await api("/courses");
      toast(`已导入 ${r.count} 门课程`);
      await adminContent();
    });
  } else if (adminTab === "settings") {
    const s = await api("/admin/settings");
    box.innerHTML = `<form id="settings-form" class="panel narrow"><h3>信用与预约规则</h3>${[
      ["min_credit", "发布 / 预约最低信用分"],
      ["complete_bonus", "完成交接双方加分"],
      ["report_penalty", "举报成立扣分"],
      ["no_show_penalty", "爽约扣分"],
      ["confirm_hours", "双方确认超时（小时）"],
    ]
      .map(([k, t]) =>
        field(
          k,
          t,
          "number",
          s[k],
          `required min="${k === "confirm_hours" ? 1 : 0}" max="${k === "confirm_hours" ? 720 : 200}"`,
        ),
      )
      .join(
        "",
      )}<p class="hint">每本教材最多一个有效预约；信用分范围0—200。爽约由管理员核实后裁定。</p><p class="error" tabindex="-1" role="alert"></p><button type="submit">保存规则</button></form>`;
    formHandler("#settings-form", async (d) => {
      await api("/admin/settings", "PUT", d);
      toast("规则已更新");
    });
  } else {
    const list = await api("/admin/logs");
    box.innerHTML = `<div class="panel table-wrap"><h3>最近500条操作记录</h3><table><thead><tr><th>时间（UTC）</th><th>操作者</th><th>操作</th><th>对象</th><th>说明</th></tr></thead><tbody>${list.map((l) => `<tr><td>${esc(l.created_at)}</td><td>${esc(l.nickname || "系统")}</td><td>${esc(l.action)}</td><td>${esc(l.entity)} #${esc(l.entity_id)}</td><td class="wrap">${esc(l.detail)}</td></tr>`).join("")}</tbody></table></div>`;
  }
}
async function reviewDialog(id) {
  const b = await api("/books/" + id);
  modal(
    "审核教材信息",
    `<div class="detail"><img src="${esc(b.images[0])}" alt="教材封面"><div><h3>${esc(b.title)}</h3><p>${esc(b.course_code)} ${esc(b.course_name)}<br>${esc(b.edition)} / ${esc(conditions[b.condition])}<br>${esc(b.notes)}</p>${price(b.price)}</div></div><div class="preview">${b.images
      .slice(1)
      .map((src) => `<img src="${esc(src)}" alt="补充图片">`)
      .join("")}</div><form id="review-form">${select("approve", "审核结果", [
      ["true", "通过"],
      ["false", "驳回"],
    ])}${textarea("reason", "审核理由（驳回时必填）", "", 'maxlength="500"')}<p class="error" role="alert" tabindex="-1"></p><button type="submit">提交审核结果</button></form>`,
  );
  formHandler("#review-form", async (d) => {
    await api("/books/" + id + "/review", "POST", {
      ...d,
      approve: d.approve === "true",
    });
    closeModal();
    toast("审核结果已保存");
    await render();
  });
}
function resolveReport(id) {
  modal(
    "处理举报或申诉",
    `<p class="hint">普通举报成立会扣分；对于“申请撤销处罚”的申诉，成立会退还原扣分且不自动重新上架。请核实证据后裁定。</p><form id="resolve-form">${select(
      "upheld",
      "处理结论",
      [
        ["false", "不成立 / 维持现状"],
        ["true", "成立 / 按举报或申诉类型执行"],
      ],
    )}<label class="check"><input type="checkbox" name="takedown" value="1">成立时同时下架教材并取消有效预约</label>${textarea("reason", "处理理由", "", 'required maxlength="1000"')}<p class="error" tabindex="-1" role="alert"></p><button type="submit">确认处理</button></form>`,
  );
  formHandler("#resolve-form", async (d) => {
    await api("/reports/" + id + "/resolve", "POST", {
      ...d,
      upheld: d.upheld === "true",
      takedown: d.takedown === "1",
    });
    closeModal();
    toast("举报已处理");
    await render();
  });
}
function resolveRsv(el) {
  modal(
    "处理交接申诉",
    `<form id="resolve-rsv-form">${select("outcome", "处理结果", [
      ["cancelled", "取消交易"],
      ["completed", "确认已完成交接"],
      ["no_show", "认定爽约"],
    ])}${select("responsible_id", "爽约责任方（仅认定爽约时生效）", [
      [el.dataset.owner, "发布者"],
      [el.dataset.buyer, "需求者"],
    ])}${textarea("reason", "核实依据与处理理由", "", 'required maxlength="500"')}<p class="error" tabindex="-1" role="alert"></p><button type="submit">确认裁定</button></form>`,
  );
  formHandler("#resolve-rsv-form", async (d) => {
    await api("/reservations/" + el.dataset.id + "/resolve", "POST", {
      ...d,
      responsible_id: +d.responsible_id,
    });
    closeModal();
    toast("申诉已处理");
    await render();
  });
}
document.addEventListener("click", async (event) => {
  const el = event.target.closest("[data-action]");
  if (!el) return;
  const act = el.dataset.action,
    id = el.dataset.id;
  try {
    if (act === "logout") {
      await api("/logout", "POST");
      await refreshMe();
      location.hash = "market";
      await render();
    } else if (act === "focus-search") {
      $("#query").focus();
      $("#query").scrollIntoView({ block: "center" });
    } else if (act === "go-publish") location.hash = "publish";
    else if (act === "detail") await detail(id);
    else if (act === "reserve") reserveDialog(id);
    else if (act === "edit") location.hash = "edit/" + id;
    else if (act === "withdraw") {
      modal(
        "下架教材",
        '<p>下架后其他同学将无法检索此教材。你可以从书架编辑后重新提交审核。</p><button data-action="confirm-withdraw" data-id="' +
          id +
          '">确认下架</button>',
      );
    } else if (act === "confirm-withdraw") {
      await api("/books/" + id + "/withdraw", "POST");
      closeModal();
      toast("教材已下架");
      await render();
    } else if (act === "rsv") await rsvAction(id, el.dataset.op);
    else if (act === "confirm-handoff") {
      await api("/reservations/" + id + "/action", "POST", {
        action: "confirm",
      });
      closeModal();
      await refreshMe();
      toast("交接确认已保存");
      await render();
    } else if (act === "rate") ratingDialog(id);
    else if (act === "report") reportDialog(id);
    else if (act === "review") await reviewDialog(id);
    else if (act === "admin-tab") {
      adminTab = el.dataset.tab;
      await admin();
    } else if (act === "appeal-report")
      reasonDialog("申请撤销处罚", async (reason) => {
        await api("/reports/" + id + "/appeal", "POST", { reason });
      });
    else if (act === "resolve-report") resolveReport(id);
    else if (act === "resolve-rsv") resolveRsv(el);
    else if (act === "retract-report") {
      await api("/reports/" + id, "DELETE");
      toast("举报已撤回");
      await render();
    } else if (act === "delete-rating") {
      await api("/ratings/" + id, "DELETE");
      toast("评价已删除");
      await render();
    } else if (act === "read-notes") {
      await api("/notifications/read", "POST");
      toast("消息已标记为已读");
      await render();
    }
  } catch (e) {
    toast(e.message);
  }
});
async function render() {
  const version = ++routeVersion;
  const route = location.hash.slice(1) || "market";
  navigation();
  if (!["market", "login", "register"].includes(route) && !user) {
    location.hash = "login";
    return;
  }
  $("#main").innerHTML = '<p class="loading">正在加载…</p>';
  try {
    if (route === "market") await market();
    else if (route === "login" || route === "register")
      loginPage(route === "register");
    else if (route === "publish" || route.startsWith("edit/"))
      await publishPage(route.split("/")[1]);
    else if (route === "mine") await mine();
    else if (route === "reservations") await reservations();
    else if (route === "profile") await profile();
    else if (route === "admin") await admin();
    else $("#main").innerHTML = empty("页面不存在", "请从上方导航继续浏览。");
  } catch (e) {
    if (version === routeVersion)
      $("#main").innerHTML = empty("暂时无法加载", e.message);
  }
}
window.addEventListener("hashchange", () => {
  closeModal();
  render();
});
(async () => {
  try {
    await refreshMe();
    courses = await api("/courses");
    await render();
  } catch (e) {
    $("#main").innerHTML = empty("服务暂不可用", e.message);
  }
})();
