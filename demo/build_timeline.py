# 生成 ffmpeg concat 清单（带时长）与同步 SRT 字幕
# 帧来源：D:/Project/Agent/demo/raw（浏览器自动化截图）
import os

RAW = "D:/Project/Agent/demo/raw"
OUT_LIST = "D:/Project/Agent/demo/frames.txt"
OUT_SRT = "D:/Project/Agent/demo/captions.srt"

HOLD = 4.5   # 关键画面停留
FAST = 1.5   # 流式过程帧

def f(name):
    return f"{RAW}/{name}"

def seq(prefix, n, start=1):
    return [f"{prefix}_f{i:02d}.png" for i in range(start, start + n)]

# (帧文件列表, 每帧时长, 字幕)
timeline = []

# 片头卡片
timeline.append((["card_title.png"], 6.0, None))

timeline.append((
    ["s0_login_f01.png", "s0_login_filled_f02.png", "s0_chat_landing_f03.png"],
    FAST, "① 登录系统 —— 单商家售后模式，admin 即品牌售后处理人"))

s1 = ["s1_type_f01.png"] + seq("s1_stream", 10, 2) + ["s1_trace_f12.png", "s1_sources_f13.png"]
durs = [FAST] * 12 + [HOLD, HOLD]
timeline.append((s1, durs, "② 知识库问答：SSE 流式输出 · LangGraph 流水线逐节点可视化 · 来源逐条可溯"))

s2 = ["s2_type_f01.png"] + seq("s2_stream", 3, 2) + ["s2_followup_f05.png"]
durs = [FAST] * 5 + [HOLD]
timeline.append((s2, durs + [HOLD][: 6 - len(s2)][: len(s2) - 5] if False else [FAST] * (len(s2) - 1) + [HOLD],
                 "③ 信息不足 → Agent 主动追问：机型未知不硬答，先给安全提醒，最多连续追问一轮"))

s3 = ["s3_type_f01.png"] + seq("s3_stream", 8, 2) + ["s3_answer_f10.png", "s3_sources_f11.png"]
durs = [FAST] * (len(s3) - 2) + [HOLD, HOLD]
timeline.append((s3, durs, "④ 补充信息后：结构化诊断 · 三分标注（知识库明确/推断/无法确认）· 机型硬过滤"))

s4 = ["s4_type_f01.png"] + seq("s4_stream", 7, 2) + ["s4_safety_f09.png"]
durs = [FAST] * (len(s4) - 1) + [HOLD]
timeline.append((s4, durs, "⑤ 高风险场景：分态安全处置（飞行中/已降落/充电中）+ 升级人工，永不自动关单"))

s5 = ["s5_type_f01.png"] + seq("s5_stream", 12, 2) + ["s5_bottom_f14.png"]
durs = [FAST] * (len(s5) - 1) + [HOLD]
timeline.append((s5, durs, "⑥ 需要售后：Agent 判定升级人工，升级提示上可一键建单"))

s6 = ["s6_modal_f01.png", "s6_draft_f02.png", "s6_edited_f01.png", "s6_submitted_f02.png"]
durs = [FAST, HOLD, FAST, HOLD]
timeline.append((s6, durs, "⑦ 服务端快照建单：机型/故障分类/安全等级由系统判定，用户确认后才提交"))

s7 = ["s7_queue_f01.png", "s7_detail_f02.png", "s7_analyzing_f03.png", "s7_panel_f04.png"]
durs = [FAST, FAST, FAST, HOLD]
timeline.append((s7, durs, "⑧ 管理端 AI Copilot：AI 诊断 · 知识证据 · SOP · 处理建议 · 回复草稿"))

s8 = ["s8_reply_f01.png", "s8_adopted_f02.png", "s8_edited_reply_f03.png", "s8_replied_f04.png"]
durs = [HOLD, FAST, FAST, HOLD]
timeline.append((s8, durs, "⑨ 人工确认：采用建议 → 修改 → 发送（AI 只预填草稿，永不自动发送）"))

s9 = ["s9_assigned_f01.png", "s9_inprogress_f01.png", "s9_resolved_f02.png", "s9_timeline_f03.png"]
durs = [FAST, FAST, HOLD, HOLD]
timeline.append((s9, durs, "⑩ 状态机流转：接单 → 处理中 → 待用户确认；AI 建议入审计流水，用户侧不可见"))

s10 = ["s10_list_f01.png", "s10_detail_f02.png", "s10_timeline_f03.png", "s10_closed_f04.png",
       "s10_closed_final.png"]
durs = [FAST, FAST, HOLD, FAST, HOLD]
timeline.append((s10, durs, "⑪ 用户确认解决 → 工单关闭：一个售后 case 的全链路机器可读（闭环完成）"))

timeline.append((["card_end.png"], 8.0, None))

# 写 concat 清单
def full_path(name):
    return name if name.startswith("card_") else f"{RAW}/{name}"

with open(OUT_LIST, "w", encoding="utf-8") as fp:
    for files, durs_, _cap in timeline:
        if isinstance(durs_, float) or isinstance(durs_, int):
            durs_ = [durs_] * len(files)
        for i, (file, d) in enumerate(zip(files, durs_)):
            fp.write(f"file '{full_path(file)}'\n")
            fp.write(f"duration {d}\n")
        # concat demuxer 要求最后一个文件重复一次声明
        fp.write(f"file '{full_path(files[-1])}'\n")

# 写 SRT（按场景聚合时间轴）
def ts(sec):
    h = int(sec // 3600); m = int(sec % 3600 // 60); s = int(sec % 60)
    ms = int(round((sec - int(sec)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

entries = []
t = 0.0
for files, durs_, cap in timeline:
    if isinstance(durs_, float) or isinstance(durs_, int):
        durs_ = [durs_] * len(files)
    span = sum(durs_)
    if cap:
        entries.append((t, t + span, cap))
    t += span

with open(OUT_SRT, "w", encoding="utf-8") as fp:
    for i, (a, b, cap) in enumerate(entries, 1):
        fp.write(f"{i}\n{ts(a)} --> {ts(b)}\n{cap}\n\n")

print(f"total duration: {t:.1f}s, captions: {len(entries)}")
missing = [file for files, durs_, _ in timeline for file in files if not os.path.exists(full_path(file))]
print("missing files:", missing if missing else "none")
