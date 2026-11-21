# neikong

财政部统一报表系统内控编报下载技能。

仓库提供技能说明、参考资料和 HTML 生成脚本。单位填报记录、附件原件和 OCR 结果按指定位置在本地归档。

## 包含的技能

| 技能 | 适用对象 | 采集页签 |
| --- | --- | --- |
| `nkbg-download-skill` | 基层单位 | 基本信息录入、单位内部控制情况 |
| `hznkbg-download-skill` | 汇总部门 | 基本信息录入、部门内部控制情况 |

两个技能均支持逐单位归档、逐题附件链接、当前模型优先 OCR、本地 OCR 补读、印章识读和离线 HTML 生成。

## 从公开仓库安装

安装时可直接从 GitHub 下载，无需 GitHub 账号、登录或令牌。在 Codex 中可以直接输入以下指令。

> 从 GitHub 仓库 cgicsj/neikong 的 main 分支安装 nkbg-download-skill 和 hznkbg-download-skill。

也可以用 Python 3 运行 Codex 技能安装器，以下为 Windows PowerShell 示例。

```powershell
$installer = "$env:USERPROFILE\.codex\skills\.system\skill-installer\scripts\install-skill-from-github.py"
python -X utf8 $installer --repo cgicsj/neikong --ref main --method download --path nkbg-download-skill hznkbg-download-skill
```

只安装一个技能时，在 `--path` 后保留相应的目录名。安装器会保留已有的同名技能。安装成功后，在 Codex 中开启新会话即可调用。

## 使用技能

先在浏览器登录财政部统一报表系统，确认账号可查看目标单位的填报明细。使用时可以指定报告年度、单位范围、数量和输出目录。

- 基层单位用 `$nkbg-download-skill 下载当前年度前 5 家基层单位的内控编报`
- 汇总部门用 `$hznkbg-download-skill 下载当前年度前 5 家汇总部门的内控编报`

每个单位单独归档，打开批次目录中的 `index.html` 可浏览单位列表，并进入各单位页面查阅填报内容、附件原件、附件全文和盖章情况。

## 仓库结构

```text
neikong/
├── nkbg-download-skill/
│   ├── SKILL.md
│   ├── references/
│   └── scripts/
└── hznkbg-download-skill/
    ├── SKILL.md
    ├── references/
    └── scripts/
```

## 校验

本地运行 `skill-creator` 的官方校验器需要 Python 3 和 `PyYAML`。在中文 Windows 下使用 UTF-8 模式。

```powershell
python -X utf8 "$env:USERPROFILE\.codex\skills\.system\skill-creator\scripts\quick_validate.py" `
  .\nkbg-download-skill

python -X utf8 "$env:USERPROFILE\.codex\skills\.system\skill-creator\scripts\quick_validate.py" `
  .\hznkbg-download-skill
```

两个技能均应返回 `Skill is valid!`。
