# neikong

财政部统一报表系统内控编报下载技能。

本仓库只保存技能说明和生成脚本，不包含单位填报记录、附件原件、OCR 结果或其他内控归档数据。

## 包含的技能

| 技能 | 适用对象 | 采集页签 |
| --- | --- | --- |
| `nkbg-download-skill` | 基层单位 | 基本信息录入、单位内部控制情况 |
| `hznkbg-download-skill` | 汇总部门 | 基本信息录入、部门内部控制情况 |

两个技能均支持逐单位归档、逐题附件链接、当前模型优先 OCR、本地 OCR 补读、印章识读和离线 HTML 生成。

## 从仓库安装

使用 Codex 的技能安装器，一次安装两个技能：

```powershell
python "$env:USERPROFILE\.codex\skills\.system\skill-installer\scripts\install-skill-from-github.py" `
  --repo cgicsj/neikong `
  --path nkbg-download-skill hznkbg-download-skill
```

也可以按 GitHub 路径安装单个技能：

```powershell
python "$env:USERPROFILE\.codex\skills\.system\skill-installer\scripts\install-skill-from-github.py" `
  --repo cgicsj/neikong `
  --path nkbg-download-skill
```

安装后，技能在当前会话的下一轮可用。若本地已经安装同名技能，安装器会中止并保留现有目录。

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

使用 `skill-creator` 的官方校验器时，在中文 Windows 下需要启用 UTF-8 模式：

```powershell
python -X utf8 "$env:USERPROFILE\.codex\skills\.system\skill-creator\scripts\quick_validate.py" `
  .\nkbg-download-skill

python -X utf8 "$env:USERPROFILE\.codex\skills\.system\skill-creator\scripts\quick_validate.py" `
  .\hznkbg-download-skill
```

两个技能均应返回 `Skill is valid!`。
