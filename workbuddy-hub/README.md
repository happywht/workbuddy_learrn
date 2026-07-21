# WorkBuddy 学习与共建站点

这是一个面向持续学习、复用和共建的多页面 WorkBuddy 指南站。当前产品分为三个相互独立的使用入口：学习中心帮助用户完成第一次成功，案例社区提供可复现的方法，贡献入口负责把已经验收的任务交给 WorkBuddy Agent 整理和发布。

## 页面结构

### 学习中心

- `index.html`：学习首页，提供工作方向、公共课程、案例预览和次级贡献入口。
- `paths/onboarding.html`：安装、工作空间、首次任务和飞书连接。
- `paths/project.html`：项目周报风险归拢。
- `paths/management.html`：合同回款预警和人员工作量验证。
- `paths/briefing.html`：周报转结论型 PPT。
- `resources/ai-evolution.html`：9 页 AI 产品演进阅读器。
- `resources/bluebook-course.html`：WorkBuddy 蓝皮书第 1-3 章连续视频课程。
- `resources/advanced-automation.html`：15 页 WorkBuddy 高阶自动化实战阅读器。

### 案例社区

- `community/index.html`：案例搜索、分类和案例列表。
- `community/case.html?id=...`：案例输入、步骤、指令、样例文件、限制与验收标准。
- `data/registry.json`：当前静态示范案例数据源。

当前版本不展示虚构评分、热度、作者或排名。真实身份、版本反馈和评价能力需要在后端与权限体系接入后开放。

### 贡献方法

- `contribute/index.html`：面向用户的任务成功后贡献入口。
- `agent-skill/SKILL.md`：供 WorkBuddy Agent 读取的打包、脱敏、范围确认和发布指导。
- `agent-skill/schemas/`：机器可读的发布包与请求结构。

贡献不设事前人工审核。Agent 必须先生成脱敏预览，询问个人、部门或组织范围，并在用户明确确认标题、类型、脱敏结果和范围后发布。平台治理采用事后下架、修订与回滚。

## 本地浏览

在项目根目录运行：

```powershell
python workbuddy-hub/serve.py --port 4173
```

然后访问 `http://127.0.0.1:4173/workbuddy-hub/`。

自定义本地服务器支持 MP4 Range 请求，视频章节定位可以正常工作；通过 HTTP 打开也能确保样例下载和浏览器剪贴板能力稳定工作。
