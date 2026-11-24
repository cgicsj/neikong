async ({row, task, file = null, offset = 0, stage = "items"}) => {
  const clean = node => node?.innerText?.trim() ?? "";
  const visible = node => node.getClientRects().length > 0 && node.getBoundingClientRect().height > 0;
  const shown = (selector, root = document) => [...root.querySelectorAll(selector)].filter(visible);
  const one = (nodes, label) => {
    if (nodes.length !== 1) throw Error(`${label}入口不唯一或不可见`);
    return nodes[0];
  };
  const wait = (probe, label) => new Promise((resolve, reject) => {
    const cleanup = () => { observer.disconnect(); clearTimeout(timer); };
    const check = () => {
      try {
        const value = probe();
        if (value) { cleanup(); resolve(value); }
      } catch (error) {
        cleanup();
        reject(error);
      }
    };
    const observer = new MutationObserver(check);
    const timer = setTimeout(() => { cleanup(); reject(Error(`${label}加载未确认`)); }, 16000);
    observer.observe(document.body, {childList: true, subtree: true, attributes: true, characterData: true});
    check();
  });
  const result = {
    unit_code: row.code, unit_name: row.name, captured_at: new Date().toISOString(),
    report_version: row.report_version, basic: [], items: [], supplementary: null, issues: [],
  };
  const basicSelector = ".ivu-collapse-item";
  const header = () => shown(".content_top").find(node =>
    [...node.querySelectorAll(".progress-span")].some(tab => clean(tab) === "评价指标打分"));
  const modal = () => shown(".ivu-modal");
  let opened = false;
  async function closeDetails() {
    if (modal().length) {
      one(shown("button", one(modal(), "附件弹窗")).filter(b => clean(b) === "确定"), "附件清单关闭").click();
    }
    await wait(() => !modal().length, "关闭附件清单");
    const container = header();
    if (container) one(shown("button", container).filter(b => clean(b) === "关闭"), "关闭明细").click();
    await wait(() => !header() && !modal().length, "关闭明细");
  }
  const slot = selector => shown(selector).find(node => node.getAttribute("rowid") === row.code);
  const signs = label => shown(".progress-span", header()).filter(node => clean(node) === label);
  const current = () => shown(".treeNode.active").find(node => node.querySelector(".title"));
  const topicRoot = () => shown(".tiWrap .pc-container.container-self").find(node =>
    shown(".pc-container:not(.container-self)", node).length);
  const supplementaryRoot = () => {
    const tabs = header();
    return shown(".ivu-tabs-tabpane-active").find(node => !node.contains(tabs))
      ?? tabs?.closest(".ivu-modal-body") ?? tabs?.parentElement?.parentElement ?? null;
  };
  const captureSupplementary = root => {
    const tabs = header();
    const tables = shown("table", root).map(table => shown("tr", table).map(line =>
      [...line.cells].map(cell => {
        const inputs = shown(controls, cell);
        return {text: clean(cell), value: inputs.length ? inputs.map(fieldValue).join("、") : null,
          colspan: cell.colSpan, rowspan: cell.rowSpan};
      })));
    const fields = shown(".ivu-form-item", root).map(item => ({
      label: clean(item.querySelector(".ivu-form-item-label,.label")),
      value: clean(item.querySelector(".ivu-form-item-content")) || clean(item),
    })).filter(item => item.label || item.value);
    const text = clean(root).replace(clean(tabs), "").trim();
    return {confirmed: true, captured_at: new Date().toISOString(), text, tables, fields};
  };
  const groupTitles = ["一、组织层面内部控制", "二、业务层面内部控制", "三、内部监督", "四、补充指标"];
  const groups = () => [...document.querySelector(".unit-questionnaire-tree")?.children ?? []]
    .filter(node => node.querySelector(".treeNode.wrapNode"));
  const groupTitle = node => clean(node.querySelector(".wrapNode .title"));
  const groupItems = node => shown(".treeNode.parentNode", node);

  async function indicatorPlan(expected) {
    const blocks = await wait(() => groups().length === groupTitles.length && groups(), "四个评价大类");
    if (blocks.some((node, index) => groupTitle(node) !== groupTitles[index])) {
      throw Error("评价大类名称或顺序与系统目录不符");
    }
    for (const block of blocks) {
      if (!groupItems(block).length) {
        one(shown(".wrapNode .arrow", block), "展开" + groupTitle(block)).click();
        await wait(() => groupItems(block).length, groupTitle(block) + "子项目");
      }
    }
    const plan = blocks.flatMap(block => groupItems(block).map(node =>
      ({node, group: groupTitle(block), title: clean(node.querySelector(".title"))})));
    if (plan.length !== expected || new Set(plan.map(item => JSON.stringify([item.group, item.title]))).size !== expected
        || plan.some(item => !item.title)) throw Error("四个大类的项目数与系统页数不一致或含重复项目");
    return plan;
  }
  const controls = "input:not([type=hidden]):not([type=password]),textarea,select,[contenteditable=true]";

  function fieldValue(input) {
    if (input.tagName === "SELECT") return [...input.selectedOptions].map(clean).join("、") || "未选";
    if (input.matches("[contenteditable=true]")) return clean(input) || "空白";
    return input.value === "" ? "空白" : input.value;
  }
  function indicatorText(node) {
    let label = clean(node);
    if (!node) return label;
    const isGray = element => {
      const rgb = getComputedStyle(element).color.match(/[\d.]+/g)?.slice(0, 3).map(Number);
      return rgb?.length === 3 && Math.min(...rgb) >= 95 && Math.max(...rgb) - Math.min(...rgb) <= 22;
    };
    for (const element of node.querySelectorAll("*")) {
      if (!visible(element) || (!element.matches(".title-instructions") && !isGray(element))) continue;
      const explanation = clean(element);
      if (explanation && explanation !== label) label = label.replace(explanation, "");
    }
    return label.replace(/^[*＊]\s*/, "").trim();
  }

  function indicatorAnswer(block, label) {
    // 查看明细 uses disabled controls, but their checked state and value are still available.
    const inputs = shown(controls, block);
    const choices = inputs.filter(input => input.type === "radio" || input.type === "checkbox")
      .map(input => ({label: clean(input.closest("label")), selected: input.checked}));
    const applicabilityOptions = new Set(["适用", "不适用"]);
    if (label.startsWith("是否适用") || (choices.length && choices.every(answer => applicabilityOptions.has(answer.label)))) {
      const selected = choices.filter(answer => answer.selected && applicabilityOptions.has(answer.label));
      return {kind: "applicability", applicability: selected.length === 1 ? selected[0].label : null};
    }

    const scoreWithUnit = /^\d+(?:\.\d+)?\s*分$/;
    if (choices.length) {
      const scoreOptions = choices.filter(answer => scoreWithUnit.test(answer.label));
      return scoreOptions.length ? {answers: scoreOptions.filter(answer => answer.selected)} : {kind: "unclassified"};
    }
    const valueFields = inputs.map(input => {
      const cell = input.closest(".multiple-blank-item");
      const label = cell ? clean(cell.previousElementSibling) : "";
      return {label, value: fieldValue(input)};
    });
    const scoreLabel = /得分|评分|分值/;
    const scoreFields = valueFields.filter(answer => scoreWithUnit.test(answer.value) || scoreLabel.test(answer.label));
    if (!scoreFields.length) return {kind: "unclassified"};
    return {answers: scoreFields.filter(answer => scoreWithUnit.test(answer.value)
      || /^\d+(?:\.\d+)?$/.test(answer.value))};
  }
  const nameOf = node => node.getAttribute("title") || clean(node);
  const busySelector = '.ivu-spin, .ivu-spin-fix, .ivu-table-loading, [aria-busy="true"]';

  async function collectUploads(button, expected, question, requested) {
    if (modal().length) throw Error("上一处弹窗尚未关闭");
    button.click();
    let dialog;
    async function readPage(page, previousPage) {
      const started = Date.now();
      let previous = null;
      let stable = 0;
      while (Date.now() - started < 16000) {
        dialog ??= modal().find(m => clean(m).includes("上传附件")
          && !m.classList.contains("ease-enter-active") && !m.classList.contains("ease-leave-active"));
        const rows = dialog ? shown(".ivu-table-row", dialog) : [];
        const active = dialog ? shown(".ivu-page-item-active", dialog) : [];
        const current = active.length ? Number(clean(active[0])) : 1;
        const names = rows.map(line => clean(line.cells?.[1]));
        const empty = dialog && shown(".ivu-table-tip, .ivu-table-empty", dialog)
          .some(node => /暂无|无数据|没有数据/.test(clean(node)));
        const signature = dialog && current === page && !dialog.matches(busySelector)
          && !shown(busySelector, dialog).length && (names.length && names.every(Boolean)
            ? JSON.stringify(rows.map(clean)) : empty && page === 1 ? "empty" : null);
        if (signature && signature !== previousPage) {
          stable = signature === previous ? stable + 1 : 1;
          if (stable >= 5 && (signature !== "empty" || Date.now() - started >= 1500)) {
            return {rows, signature};
          }
        } else {
          stable = 0;
        }
        previous = signature;
        await new Promise(resolve => setTimeout(resolve, 200));
      }
      throw Error("附件清单明细加载未确认");
    }
    try {
      const entries = [];
      let previousPage = null;
      for (let page = 1; ; page++) {
        const {rows, signature} = await readPage(page, previousPage);
        for (const line of rows) {
          const name = clean(line.cells[1]);
          const metadata = [...line.cells].slice(2).map(clean);
          const buttons = shown("button", line).filter(b => clean(b) === "下载" && !b.disabled);
          if (buttons.length !== 1) result.issues.push(`${question} / ${name}：下载入口不可用或不唯一`);
          const entry = {name, page, metadata};
          if (requested && entries.length === requested.index) {
            if (JSON.stringify(entry) !== JSON.stringify(requested.entry)) throw Error("附件清单与待下载条目不一致");
            one(buttons, "单件附件下载").click();
            return {requested: true};
          }
          entries.push(entry);
        }
        const next = shown(".ivu-page-next", dialog);
        if (!next.length || next[0].classList.contains("ivu-page-disabled")) break;
        previousPage = signature;
        one(next, "附件下一页").click();
      }
      if (requested) throw Error("未找到待下载的附件条目");
      if (expected.length && JSON.stringify([...expected].sort()) !== JSON.stringify(entries.map(f => f.name).sort())) {
        result.issues.push(`${question}：题面附件列表与弹窗不一致`);
      }
      return entries;
    } finally {
      if (dialog) {
        one(shown("button", dialog).filter(b => clean(b) === "确定"), "关闭附件清单").click();
        await wait(() => !modal().length, "关闭附件清单");
      }
    }
  }

  try {
    if (stage === "close") {
      await closeDetails();
      return result;
    } else if (stage === "open") {
      if (header() || modal().length) throw Error("有明细或弹窗已打开，请核查后再继续");
      const form = document.querySelector("form.ivu-form");
      if (!form || ![...form.querySelectorAll("input")].some(input => input.value === task)
          || ![...form.querySelectorAll(".ivu-tag-text")].some(node => clean(node) === "基层单位")) {
        throw Error("查询任务或基层单位筛选与名录不一致");
      }
      const pager = document.querySelector(".ivu-page");
      const currentPage = Number(clean(pager?.querySelector(".ivu-page-item-active")));
      if (currentPage !== row.page) {
        const direct = shown(".ivu-page-item", pager).find(node => Number(clean(node)) === row.page);
        if (direct) {
          direct.click();
        } else {
          const input = one(shown(".ivu-page-options-elevator input", pager), "页码跳转");
          input.value = String(row.page);
          input.dispatchEvent(new Event("input", {bubbles: true}));
          input.dispatchEvent(new KeyboardEvent("keyup", {key: "Enter", keyCode: 13, bubbles: true}));
        }
        await wait(() => Number(clean(pager.querySelector(".ivu-page-item-active"))) === row.page, "目标列表页");
      }
      const main = await wait(() => slot(".body--wrapper tr[rowid]"), "目标单位行");
      const mainCells = [...main.cells].map(node => node.textContent.trim());
      const indexes = row.column_indexes;
      if (mainCells.length !== row.cells.length || mainCells[indexes["单位名称"]] !== row.name
        || mainCells[indexes["单位代码"]] !== row.code
        || !/^(基层|基层单位)$/.test(mainCells[indexes["单位类型"]])
        || (mainCells[indexes["上报日期"]] || null) !== row.report_version
        || Number(clean(pager.querySelector(".ivu-page-item-active"))) !== row.page) throw Error("单位行身份、报送时间或页码改变");
      const actions = shown(".fixed-right--wrapper tr[rowid]").find(node => node.getAttribute("rowid") === row.code);
      if (!actions || !shown(".button_text", actions).some(node => clean(node) === "更多")) {
        throw Error("对应操作列未确认开展评价");
      }
      one(shown(".button_text", actions).filter(node => clean(node) === "查看明细"), "查看明细").click();
      return result;
    } else if (stage === "basic") {
      await wait(() => header() && clean(header()).includes(row.name), "评价明细和单位身份");
      opened = true;
      if (!shown(basicSelector).length) {
        const basicTab = one(signs("基本信息"), "基本信息");
        (basicTab.querySelector("span") ?? basicTab).click();
      }
      await wait(() => shown(basicSelector).some(group =>
        clean(group.querySelector(".collpse-panel-title-icon")) === "单位基本信息"
        && shown(controls, group).some(input => input.value === row.name)), "基本信息和单位身份");
      result.basic = shown(basicSelector).filter(group => shown("table", group).length).map(group => ({
        title: clean(group.querySelector(".collpse-panel-title-icon")),
        rows: shown("tr", group).map(line => [...line.cells].map(cell => {
          const inputs = shown(controls, cell);
          return {text: clean(cell), colspan: cell.colSpan, rowspan: cell.rowSpan,
            value: inputs.length ? inputs.map(fieldValue).join("、") : null};
        })),
      }));
      if (!result.basic.some(group => group.rows.flat().some(cell => cell.value === row.name))) {
        throw Error("明细基本信息的单位名称与列表不一致");
      }
      return result;
    } else if (stage === "scores") {
      if (!header() || !clean(header()).includes(row.name) || modal().length) throw Error("明细身份或状态无法确认");
      one(signs("评价指标打分"), "评价指标打分").click();
      return result;
    } else if (stage === "supplementary") {
      if (!header() || !clean(header()).includes(row.name) || modal().length) throw Error("明细身份或状态无法确认");
      opened = true;
      const root = supplementaryRoot();
      if (!root) throw Error("无法定位补充说明内容区域");
      const previous = clean(root);
      const tab = one(signs("补充说明"), "补充说明");
      tab.click();
      const ready = await wait(() => {
        const currentRoot = supplementaryRoot();
        const selected = tab.getAttribute("aria-selected") === "true"
          || /(?:^|\s)(?:active|current|selected)(?:\s|$)/.test(tab.className);
        return currentRoot && (selected || clean(currentRoot) !== previous)
          && !shown(busySelector, currentRoot).length ? currentRoot : null;
      }, "补充说明内容");
      result.supplementary = captureSupplementary(ready);
      return result;
    } else {
      if (!header() || modal().length || !shown(".content_top").some(node => clean(node).includes(row.name))) {
        throw Error("续采时当前明细无法确认");
      }
      opened = true;
    }
    const title = await wait(() => shown(".titleSection").find(node => /共\s*\d+\s*页/.test(clean(node))), "指标页总数");
    result.score_summary = clean(title);
    result.expected_items = Number(result.score_summary.match(/共\s*(\d+)\s*页/)[1]);
    const plan = await indicatorPlan(result.expected_items);
    result.indicator_plan = plan.map(({group, title}) => ({group, title}));
    const order = offset + 1;
    if (order <= result.expected_items) {
      let uploadIndex = -1;
      const target = plan[offset];
      if (current() !== target.node) {
        const previous = topicRoot();
        const previousText = clean(previous);
        target.node.querySelector(".title").click();
        await wait(() => current() === target.node && topicRoot()
          && (topicRoot() !== previous || clean(topicRoot()) !== previousText), target.title + "正文");
      }
      const root = await wait(topicRoot, "当前指标内容");
      const section = {
        order, title: target.title, group: target.group, score: clean(target.node),
        fields: [],
      };
      result.items.push(section);
      for (const topic of shown(".pc-container:not(.container-self)", root)) {
        const block = topic.querySelector(":scope > div > .question-content-class");
        if (!block) {
          const heading = indicatorText(topic);
          if (topic.classList.contains("notTopic") && heading) section.fields.push({heading});
          else if (clean(topic)) result.issues.push(`${section.title}：出现未识别题型`);
          continue;
        }
        if (block.classList.contains("file-upload-question")) {
          uploadIndex++;
          if (file && file.field !== uploadIndex) continue;
          const label = "附件";
          const question = `${section.title} / 第${section.fields.filter(field => field.kind === "attachment").length + 1}处附件`;
          const field = {kind: "attachment", label, attachments: [], list_confirmed: false};
          const expected = shown(".fileName", block).map(nameOf);
          const buttons = shown(".uploadWrapBtn", block).filter(n => clean(n) === "查看附件");
          try {
            const files = await collectUploads(one(buttons, "逐题查看附件"), expected, question, file);
            if (file) {
              result.download_requested = files.requested;
              return result;
            }
            field.attachments = files;
            field.list_confirmed = true;
          } catch (error) {
            if (file) throw error;
            result.issues.push(`${question}：${error.message}`);
          }
          section.fields.push(field);
        } else {
          const label = indicatorText(block.parentElement.querySelector(":scope > .html-control"));
          if (label) {
            section.fields.push({label, ...indicatorAnswer(block, label)});
          } else {
            result.issues.push(`${section.title}：指标题干未识别`);
          }
        }
      }
    }
  } catch (error) {
    result.issues.push(error.message);
  } finally {
    try {
      if (opened && (stage === "supplementary" || result.issues.length && result.items.length === 0)) await closeDetails();
    } catch (error) {
      result.issues.push(error.message);
    }
  }
  return result;
}
