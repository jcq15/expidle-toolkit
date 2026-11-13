# Exponential Idle 小游戏工具

用电脑读取 Android 上的 Exponential Idle 棋盘，计算解法，并可通过 ADB 完成点击。第一版支持 Arrow Puzzle 的**数字显示模式**。

| 难度 | 棋盘 | 数字范围 |
| --- | --- | --- |
| 简单 `easy` | 3 × 3 方格 | 1–4 |
| 中等 `medium` | 4 × 4 方格 | 1–4 |
| 困难 `hard` | 37 格六边形 | 1–2 |
| 专家 `expert` | 37 格六边形 | 1–6 |

点一格会让它和相邻格各加 1，达到上限后回到 1。方格棋盘包括对角邻居，六边形棋盘包括最多六个相邻格。程序找出总点击次数最少的解。

## 安装

需要 Python 3.11 或更新版本、[Android SDK Platform Tools](https://developer.android.com/tools/releases/platform-tools) 和支持 USB 调试的 Android 设备。把 `adb` 放进 PATH。也可以用 `expidle --adb <路径> ...` 指定。

从项目目录运行。Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\expidle.exe --help
```

macOS / Linux：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/expidle --help
```

下面用 `expidle` 简写。请使用上面对应的可执行文件路径，或激活虚拟环境。校准窗口需要 Tk。部分 Linux 发行版需要另装 `python3-tk`。命令行和模拟测试可独立于 Tk 运行。Windows 已通过四种难度的实机验证。项目附带 Windows、macOS 和 Linux 的测试配置。iOS 不适用。

## 连接与校准

1. 打开手机的 USB 调试，用数据线连接电脑，在手机上允许这台电脑调试。`adb devices` 应显示 `device`。有多台设备时，在子命令前加 `--serial <序列号>`。
2. 手动打开 Arrow Puzzle，选择难度，在齿轮设置里打开数字显示。建议同时开启灰度。让棋盘无遮挡，保持同一方向、分辨率和主题。
3. 启动校准窗口。依次点最左、最右、最上、最下的**格子中心**。确认标记落在各格中心。选中格子后按对应数字键，每种数字至少标一个，可以标多个提高稳定性。保存前核对识别结果。遇到棋盘缺某个数字，换一盘再校准。

```sh
expidle arrow calibrate --difficulty expert --profile local/expert.json
expidle arrow solve --profile local/expert.json --dry-run --overlay local/preview.png
```

校准文件按难度和显示设置区分。棋盘变大、旋转、换了主题或识别失败时，重新校准。输出文件已存在时请换文件名。可用 [scrcpy](https://github.com/Genymobile/scrcpy) 旁观，例如 `scrcpy --no-control --no-audio`。程序本身直接通过 ADB 取原始截图，不依赖投屏窗口。

## 点击与校验

```sh
# 首次试一次，确认后最多点 1 下
expidle arrow solve --profile local/expert.json --step --limit 1

# 预览计划并输入 APPLY 后执行，默认每批最多 8 下
expidle arrow solve --profile local/expert.json --apply

# 减少每批点击数，适合动画较慢或想观察过程时
expidle arrow solve --profile local/expert.json --apply --batch-size 4
```

默认只预览。运行中保持游戏在前台，不要同时操作手机。每批都会检查棋盘是否符合预期。识别失败、屏幕尺寸改变或棋盘出现意外时会停止，不会自动重试点击。可以按 Ctrl+C 中断，已发送到手机的那批点击可能仍会执行完。单盘模式只操作当前棋盘。

离线也能校准和预览。先截屏，然后在两个命令中加 `--image local/board.png`：

```sh
expidle capture local/board.png
expidle arrow solve --image local/board.png --profile local/expert.json --overlay local/offline.png
```

## 专家刷分

打开专家数字棋盘后，用 `--rounds` 指定要完成的局数。也可从专家结算页开始，屏幕上已经解完的那盘不计入本次局数。

```sh
# 预览，不发点击
expidle arrow farm --profile local/expert.json --farm-profile local/farm.json --rounds 10

# 输入 FARM 一次，随后自动完成 10 局
expidle arrow farm --profile local/expert.json --farm-profile local/farm.json --rounds 10 --apply
```

每局按批求解。确认所有格子都是 1 且底部出现奖励文字后，才点击奖励按钮打开下一局。每次开局后会确认新棋盘和进行中的按钮。达到指定局数时停在最后一局结算页。识别异常时打印已完成局数并停止。这里的局数按已确认的结算页计数，星星数量由游戏决定。

第一次使用需要校准奖励按钮。用 `expidle capture` 保存一张正在玩的专家棋盘和同一盘解完后的结算页，查看两张原始截图中底部按钮文字的像素坐标。用两个矩形分别框住进行中的文字和结算文字，坐标顺序为左、上、右、下。下面坐标来自一台 1440 × 3120 的手机，请按截图替换。使用与专家棋盘校准相同的主题、语言和显示设置。奖励文字变化导致无法匹配时，用新的结算截图校准。

```sh
expidle arrow calibrate-farm --profile local/expert.json --farm-profile local/farm.json --active-image local/active.png --solved-image local/solved.png --active-box 527 2745 717 2805 --reward-box 380 2745 855 2805
```

## 开发

```sh
python -m pip install -e .
python -m unittest discover -s tests -v
```

`adb.py` 管截图和点击，`core.py` 定义棋盘读取、计划、状态预测和执行校验接口，`games/arrow.py` 和 `games/arrow_screen.py` 分别实现 Arrow 的规则和识别。求解器把每个格的点击数作为变量，求同余方程的解并选择点击总数最小的一组。数字华容道和环面谜题可用同一截图和执行接口实现自己的棋盘模块。

贡献时请附对应难度、平台、截图尺寸和最小复现步骤。截图和校准文件放在被 Git 忽略的 `local/`，报告问题前请裁掉通知和个人信息。自动化测试用程序绘制的棋盘，不需要连接手机。建议发布时采用 MIT 许可证，见 [LICENSE.proposed](LICENSE.proposed)，待仓库所有者确认。

This independent project reads and solves Exponential Idle's Android Arrow Puzzle in numeric mode. Calibrate once per difficulty and display setup. Preview is the default. Explicitly select step or batch mode to send taps.
