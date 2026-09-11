# 环境一键加载脚本（Windows）

> **解决两件事**：① 双击一下，开一个已经配好 `API_KEY` / `BASE_URL` / `MODEL` 的终端，直接跑每周的代码；
> ② 顺手把控制台修成真 UTF-8，避开 Windows 上那个"中文变乱码 + JSON 解析莫名报错"的坑（详见[第 4 步](#第-4-步--确认-utf-8-已生效))。
>
> 关掉窗口，一切蒸发——不写注册表、不落 `.env` 文件、不用重启 VS Code。

## 🔴 第一条规矩：先复制出去，别在仓库里改

**仓库里的这份是模板，只有占位符。请把它复制到仓库之外的目录，再填你的真实 Key。**

```bat
copy start-env-windows.bat  C:\Users\你的用户名\llm-env\start.bat
```

然后在 **`C:\Users\你的用户名\llm-env\start.bat`** 上右键编辑、填参数、双击运行。

为什么这么麻烦：

| 风险 | 说明 |
|---|---|
| **误提交** | 在仓库内改完，一个 `git add .` 就把 Key 推上 GitHub。`.gitignore` 挡不住你手动 `git add -f` |
| **扫盘脚本** | 2025-08 的 s1ngularity 攻击专门扫明文配置文件，从 1079 台机器偷走 2349 个凭证 |
| **编辑器备份** | 很多编辑器会在同目录留 `.bak` / `~` 临时文件，同样可能进版本库 |

**如果你已经在仓库内填了 Key**：立刻改回占位符，然后去中转站后台**作废并重新生成**。git 历史里的东西删不干净，换 Key 是唯一可靠的补救。

配套动作（比换目录更重要）：**给中转站 Key 设额度上限**。换个存放位置防的是"不被拿走"，额度上限防的是"拿了也没多少"。

## ⚠️ 适用系统：仅 Windows

| 系统 | 怎么办 |
|---|---|
| **Windows 10 / 11** ✅ | 用本目录的 `start-env-windows.bat` |
| macOS / Linux | 直接 `export`，或 `direnv`；把变量写进 `~/.zshrc` 也行（明文风险自担） |
| Git Bash（Windows） | 也能用，但**必须在 cmd / PowerShell 里双击启动**，在 Git Bash 里 `./start.bat` 也能跑 |

## 三步上手

### 第 1 步 · 改 3 个参数（必须）

右键 `start-env-windows.bat` → **编辑**，找到这一段：

```bat
set "API_KEY=PASTE_YOUR_KEY_HERE"
set "BASE_URL=https://your-relay.com/v1"
set "MODEL=your-model-name"
```

| 参数 | 填什么 | 常见错误 |
|---|---|---|
| `API_KEY` | 你的中转站 / 厂商 Key | 别提交进 git；别粘到聊天里 |
| `BASE_URL` | **只到 `/v1` 为止** | ❌ 带 `/chat/completions` 会拼成 `/v1/chat/completions/chat/completions` 然后 400 |
| `MODEL` | **中转站实际支持的模型名** | ❌ 抄官方文档的模型名，中转站往往改过名。用 `curl "$env:BASE_URL/models"` 列一下 |

`API_KEY` / `BASE_URL` / `MODEL` 没改的话，脚本启动时会逐条打 `[!] ... is still the placeholder`。

> 脚本**不设项目路径**：双击后它停在自己所在的目录，你再自己 `cd` 到当周的文件夹。
> 这是刻意的——把本机仓库绝对路径写进模板，等于把个人目录结构公开，还容易误提交。

### 第 1.5 步 · 可选：指定一个 Python 3.9+（3.8 用户建议做）

bat 里还有一个**可选**参数，默认留空：

```bat
set "PYTHON_HOME="
```

| 项 | 说明 |
|---|---|
| **默认值** | 空 = 用你系统里的 `python` |
| **什么时候要填** | `python --version` 显示低于 3.9 |
| **填什么** | 装了 `python.exe` 的**那个文件夹**，不是 `python.exe` 本身 |
| **为什么要填** | Python 3.8 已于 2024-10 停止维护。W05 的 pgvector、W08 的 LangGraph 在 3.8 上已经装不上了 |

不确定自己有哪些 Python，先列出来：

```powershell
where.exe python
```

填好之后，脚本启动会多打一行，用它确认生效：

```
    python      = Python 3.13.12
```

> ⚠️ **这不是项目路径。** 本脚本刻意不设任何项目目录（见上一节）。`PYTHON_HOME` 是 **Python 解释器**的安装目录——纯本机信息，**只填在你复制到仓库外的那份 bat 里**，不要提交。

### 第 2 步 · 保存，注意编码

| 项 | 要求 | 为什么 |
|---|---|---|
| **行尾** | 必须 **CRLF** | 仓库里这个文件就是 CRLF 提交的（其它文件是 LF）。用记事本编辑保存通常没问题 |
| **编码** | ANSI / GBK 或 UTF-8 无 BOM 均可 | 脚本注释**刻意全用英文**，就是为了绕开 GBK/UTF-8 打架。你要加中文注释就得自己保证编码一致 |

### 第 3 步 · 双击

会打开一个已配好变量的 shell（停在你自己放 bat 的那个目录）。先验证一下，再 `cd` 到当周文件夹：

```powershell
echo $env:API_KEY; echo $env:BASE_URL; echo $env:MODEL
```

然后直接跑每周的代码，不用再 export 任何东西。

### 第 4 步 · 确认 UTF-8 已生效（可选，30 秒）

脚本启动时会打一行：

```
  console encoding = utf-8
```

看到 `utf-8` 就成了。这行不是装饰——**它是 week-01 踩坑 #4 的解药**。

Windows PowerShell 5.1 解码外部程序（`curl.exe`）输出时，用的是**旧版 OEM 代码页**（中文机器上是 936 = GBK），不是 UTF-8。API 返回的却是 UTF-8，于是：

```
归 = E5 BD 92   --按 GBK 解读-->   三个毫不相干的汉字
```

更阴的是，错解之后字节数对不上，JSON 字符串的**收尾引号会被一起吃掉**，于是：

```powershell
curl.exe ... | ConvertFrom-Json
# ConvertFrom-Json : 传入的对象无效，应为":"或"}"。 (270): ...
```

你会去查解析器，**解析器是无辜的——字节在它上游就被毁了**。

脚本为此做了这些（全部只对当前窗口生效，没有一处写进注册表或系统设置）：

| 设置 | 管什么 |
|---|---|
| `[Console]::OutputEncoding` | PowerShell 如何**解码** curl.exe 等原生程序吐出来的字节 |
| `[Console]::InputEncoding` | 你粘贴 / 键入的内容如何解码 |
| `$OutputEncoding` | PowerShell 如何**编码**管道喂给原生命令的文本 |
| `chcp 65001` | cmd 自身的代码页（PowerShell 启动时继承） |
| `PYTHONUTF8=1`、`PYTHONIOENCODING=utf-8` | Python 往控制台或管道写中文时不再用 cp936，避免 `UnicodeEncodeError` |

> PowerShell 7（`pwsh`）默认就是 UTF-8，不需要这些。如果你装了 pwsh 并改用它，这几行对你无害但也没用。

**想亲手证明它有用**，跑这个单变量对照——同一条命令，只改解码器这一个东西：

```powershell
# ① 还原成"会出问题的状态"
[Console]::OutputEncoding = [System.Text.Encoding]::GetEncoding(936)
(curl.exe -s "$env:BASE_URL/chat/completions" -H "Authorization: Bearer $env:API_KEY" -H "Content-Type: application/json" -d "@req_nonstream.json" | ConvertFrom-Json).usage

# ② 只改解码器，其它一字不动
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
(curl.exe -s "$env:BASE_URL/chat/completions" -H "Authorization: Bearer $env:API_KEY" -H "Content-Type: application/json" -d "@req_nonstream.json" | ConvertFrom-Json).usage
```

预期结果：① 报 `ConvertFrom-Json : 传入的对象无效`，② 正常打印 usage。同一份字节流，两种命运——这就是根因。

> 如果 ① 在你机器上也是正常的，说明控制台代码页本来就是 65001（VS Code 集成终端通常会自己设，Windows Terminal 也是），那这节对你无效，跳过即可。
> 判断依据：直接查 `[Console]::OutputEncoding.WebName`，显示 `utf-8` 就没事。

## 原理（一句话）

```
cmd 里 set  →  启动 powershell.exe（子进程）  →  自动继承  →  再调 bash / python，又继承一层
```

环境变量是**向下继承**的：父进程给子进程，不会向上传播。所以这些值只活在这一条进程链里——窗口一关，全没了。

类比 Laravel 的 `.env`：框架替你 `putenv`；这里 `set` 干的是同一件事，只是作用域限定在一个窗口。

## 安全提醒（比"怎么存"更重要）

| 做法 | 说明 |
|---|---|
| **给中转站 Key 设额度上限** | 唯一能把损失封死的硬边界。加密存储防的是"不被拿走"，额度上限防的是"拿了也没多少" |
| 不要提交真实 Key | 本仓库 `.gitignore` 已忽略 `.env`；这个 bat **只放占位符**，别把填好的版本 commit |
| 不要把 Key 粘进对话 / issue | 那样数据就离开本机了，风险高于任何明文文件 |
| 定期轮换 | 学习用的 Key 每月换一次即可 |

> 说到"安全"：**换个存放位置不等于换权限边界**。同一个 Windows 账号下，任何进程（包括我、包括投毒的 npm 包）都能读到环境变量。环境变量真正的价值只有一个——**它不在文件系统里**，所以只会 `glob('.env')` 扫盘的脚本拿不到。详见 [week-01/DIALOGUE-QA.md](../week-01/DIALOGUE-QA.md) 里 Q9~Q13 那几轮。

## 常见问题

| 现象 | 原因 / 解法 |
|---|---|
| 双击后窗口一闪就没了 | 路径填错会 `pause`；如果没 pause 就闪退，在文件末尾加一行 `pause` 看报错 |
| `[!] BASE_URL looks like a full endpoint` | 把 `/chat/completions` 砍掉，只留到 `/v1` |
| PowerShell 里报"禁止运行脚本" | 跟本文件无关（它是 bat 不是 ps1）。真遇到就 `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| 一堆莫名的参数绑定错误 | **写 `curl.exe` 不是 `curl`**——PowerShell 5.1 里 `curl` 是 `Invoke-WebRequest` 的别名 |
| 中文乱码 + `ConvertFrom-Json` 报错 | `.bat` 已自动设好 UTF-8；如果你是在别的窗口跑的，手动执行一次 `[Console]::OutputEncoding = [System.Text.Encoding]::UTF8`。根因见[第 4 步](#第-4-步--确认-utf-8-已生效) |
| 命令没输出也没报错 | 别用 `-s`，用 `-sS`。`-s` 会把错误信息一起吞掉 |
| Python 打印中文报 `UnicodeEncodeError` | `PYTHONUTF8=1` 没设上；若在别的窗口跑，手动 `$env:PYTHONUTF8=1` |
| 填了 `PYTHON_HOME`，`python --version` 却没变 | 填的是**文件夹**不是 `python.exe`；或那目录下确实没有 `python.exe`——脚本会打 `[!] PYTHON_HOME is set but python.exe was not found in it.` |
| 同一个窗口反复双击 bat | PATH 会被重复追加（不影响功能，但越来越长）。每次新开窗口双击即可 |
| 改了 `chcp 65001` 后 bat 输出怪字符 | 你用的是 Windows 7/8，或往脚本里加了中文注释。把 `chcp` 那行注释掉即可——PowerShell 那三行才是关键 |

## 许可

代码 MIT，文档 CC BY-NC-SA 4.0。
