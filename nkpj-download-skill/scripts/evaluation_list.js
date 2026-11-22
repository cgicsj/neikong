async () => {
  const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
  const clean = node => node?.textContent.trim() ?? "";
  const form = document.querySelector("form.ivu-form");
  const task = [...form.querySelectorAll("input")].map(input => input.value)
    .find(value => /年度.*评价/.test(value));
  if (!task || ![...form.querySelectorAll(".ivu-tag-text")].some(tag => clean(tag) === "基层单位")) {
    throw Error("请先在单位评价复核查询基层单位，并确认评价年度");
  }
  const pager = document.querySelector(".ivu-page");
  const number = node => Number(clean(node).match(/\d+/)?.[0]);
  const total = number(pager?.querySelector(".ivu-page-total"));
  const pageNumber = () => number(pager.querySelector(".ivu-page-item-active"));
  const mainRows = () => [...document.querySelectorAll(".body--wrapper tr[rowid]")];
  const firstCode = () => mainRows()[0]?.getAttribute("rowid");
  const pageSize = () => number(pager.querySelector(".ivu-select-selected-value"));
  const ready = async (page, previous) => {
    for (let retry = 0; retry < 60; retry++) {
      if (pageNumber() === page && (total === 0 || (firstCode() && firstCode() !== previous))
          && mainRows().length === Math.min(pageSize(), total - (page - 1) * pageSize())) return;
      await pause(150);
    }
    throw Error(`第 ${page} 页未加载到预期行数。检查分页大小和虚拟滚动。`);
  };
  if (!Number.isInteger(total) || !pageSize()) throw Error("无法确认查询总数或每页条数");
  if (pageNumber() !== 1) {
    const first = [...pager.querySelectorAll(".ivu-page-item")].find(node => clean(node) === "1");
    if (!first) throw Error("缺少第一页入口");
    const previous = firstCode();
    first.click();
    await ready(1, previous);
  } else {
    await ready(1);
  }
  const headers = [...document.querySelectorAll(".vxe-table--header-wrapper .vxe-header--row")]
    .find(row => [...row.cells].some(cell => clean(cell) === "单位代码"));
  if (!headers) throw Error("未找到单位评价列表列头");
  const columns = [...headers.cells].map(clean);
  while (columns.at(-1) === "") columns.pop();
  const codeIndex = columns.indexOf("单位代码");
  const nameIndex = columns.indexOf("单位名称");
  const typeIndex = columns.indexOf("单位类型");
  if ([codeIndex, nameIndex, typeIndex].includes(-1)) throw Error("单位身份列缺失");

  const rows = [];
  const pages = Math.max(1, Math.ceil(total / pageSize()));
  for (let page = 1; page <= pages; page++) {
    for (const row of mainRows()) {
      const cells = [...row.cells];
      const code = row.getAttribute("rowid");
      if (cells.length !== columns.length || clean(cells[codeIndex]) !== code
          || !/^(基层|基层单位)$/.test(clean(cells[typeIndex]))) {
        throw Error(`第 ${page} 页身份或筛选不一致`);
      }
      const actions = [...cells.at(-1).querySelectorAll(".button_text")].map(clean);
      rows.push({page, code, name: clean(cells[nameIndex]), cells: cells.map(clean),
        eligible: actions.includes("更多"), has_detail: actions.includes("查看明细")});
    }
    if (page === pages) break;
    const next = pager.querySelector(".ivu-page-next:not(.ivu-page-disabled)");
    if (!next) throw Error(`第 ${page} 页缺少下一页`);
    const previous = firstCode();
    next.click();
    await ready(page + 1, previous);
  }
  if (rows.length !== total || new Set(rows.map(row => row.code)).size !== total) {
    throw Error("逐页名录有缺失或重复");
  }
  return {task, total, page_size: pageSize(), columns, rows};
}
