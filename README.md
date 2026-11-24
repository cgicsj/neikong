# neikong

财政部统一报表系统内控编报和单位评价下载技能。

仓库提供技能说明、参考资料和 HTML 生成脚本。单位填报记录、附件原件和 OCR 结果按指定位置在本地归档。

## 包含的技能

| 技能 | 适用对象 | 采集页签 |
| --- | --- | --- |
| `nkbg-download-skill` | 基层单位 | 基本信息录入、单位内部控制情况 |
| `hznkbg-download-skill` | 汇总部门 | 基本信息录入、部门内部控制情况 |
| `nkpj-download-skill` | 基层单位 | 基本信息、评价指标打分、补充说明 |

编报技能支持逐单位归档、逐题附件链接、当前模型优先 OCR、本地 OCR 补读、印章识读和离线 HTML 生成。单位评价技能采集基本信息、评价指标打分和补充说明；评价指标页的附件逐题读取并本地识读，不从查询结果批量下载报告或附件。

## 从公开仓库安装

安装时可直接从 GitHub 下载，无需 GitHub 账号、登录或令牌。在 Codex 中可以直接输入以下指令。

> 从 GitHub 仓库 cgicsj/neikong 的 main 分支安装 nkbg-download-skill、hznkbg-download-skill 和 nkpj-download-skill。

也可以用 Python 3 运行 Codex 技能安装器，以下为 Windows PowerShell 示例。

```powershell
$installer = "$env:USERPROFILE\.codex\skills\.system\skill-installer\scripts\install-skill-from-github.py"
python -X utf8 $installer --repo cgicsj/neikong --ref main --method download --path nkbg-download-skill hznkbg-download-skill nkpj-download-skill
```

只安装一个技能时，在 `--path` 后保留相应的目录名。安装器会保留已有的同名技能。安装成功后，在 Codex 中开启新会话即可调用。

在其他支持 `SKILL.md` 的 Agent 中，将所需技能的整个目录复制到该平台的技能目录，保留 `references/` 和 `scripts/`。在线采集所需的浏览器能力按下节确认。

## 使用技能

### 使用前准备

| 前置条件 | 如何确认 |
| --- | --- |
| 系统登录和查看权限 | 在 Agent 能操作的浏览器里登录财政部统一报表系统，确认能打开目标年度和范围内的「查看明细」。系统要求内网或 VPN 时，先接入相应网络。 |
| 浏览器 Agent 或自动化工具 | 可以操作该登录会话，读取表单、切换页签、查看附件列表并下载原件。下载文件要能被 Agent 读取。各平台可使用自己的浏览器工具。 |
| 本地运行环境 | 准备可读写的输出目录和 Python 3.9 或以上版本，用于生成 HTML 和执行下载后校验。 |
| 附件识读能力 | 能打开或解析下载文件，并渲染扫描件。扫描文字和印章可用图像识读或中文 OCR 处理。 |

只做离线校验时，保留批次的 `source/名录.json`、单位的 `record.json`、附件原件和独立取得的 `source/portal-check.json`，再运行归档生成器生成 HTML 与核验记录。缺少网页复核记录的旧档标记为「待复核」。云端 Agent 如无法访问系统或已登录会话，可用已有材料执行离线校验。

### 调用示例

使用时可以指定报告年度、单位范围、数量和输出目录。

- 基层单位用 `$nkbg-download-skill 下载当前年度前 5 家基层单位的内控编报`
- 汇总部门用 `$hznkbg-download-skill 下载当前年度前 5 家汇总部门的内控编报`
- 基层单位评价用 `$nkpj-download-skill 下载当前年度基层单位内控评价的基本信息、评价指标打分和补充说明`

每个单位单独归档，打开批次目录中的 `index.html` 可浏览单位列表并进入单位明细。基层评价页面仅含基本信息、评价指标打分和补充说明；其余编报技能展示相应填报内容、附件原件、附件全文和盖章情况。

下载后会独立复核网页，并核对归档字段、附件原件和离线 HTML。校验脚本直接保存每个单位的 `verification.json`，总目录列出校验结果。旧归档如缺少校验证据，需回源补齐。确认的网页与附件内容差异按原样保留，列为审核提示。

## 仓库结构

```text
neikong/
├── nkbg-download-skill/
│   ├── SKILL.md
│   ├── references/
│   └── scripts/
├── hznkbg-download-skill/
│   ├── SKILL.md
│   ├── references/
│   └── scripts/
└── nkpj-download-skill/
    ├── SKILL.md
    ├── references/
    └── scripts/
```

## 检查技能文件

本地运行 `skill-creator` 的官方校验器需要 Python 3 和 `PyYAML`。在中文 Windows 下使用 UTF-8 模式。

```powershell
python -X utf8 "$env:USERPROFILE\.codex\skills\.system\skill-creator\scripts\quick_validate.py" `
  .\nkbg-download-skill

python -X utf8 "$env:USERPROFILE\.codex\skills\.system\skill-creator\scripts\quick_validate.py" `
  .\hznkbg-download-skill

python -X utf8 "$env:USERPROFILE\.codex\skills\.system\skill-creator\scripts\quick_validate.py" `
  .\nkpj-download-skill
```

三个技能均应返回 `Skill is valid!`。
