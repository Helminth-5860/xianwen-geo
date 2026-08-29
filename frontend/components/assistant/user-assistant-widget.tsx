"use client";

import { CloseOutlined, SendOutlined } from "@ant-design/icons";
import { Button, Input, Typography } from "antd";
import { usePathname } from "next/navigation";
import { useMemo, useState } from "react";

import { useSubjectWorkspace } from "@/components/subject-workspace-context";

const assistantLogoSrc = "/assistant/xianwen-ai-logo.webp";
const assistantMascotSrc = "/assistant/xianwen-ai-mascot.webp";

type PageGuide = Readonly<{
  label: string;
  description: string;
  next: string;
  nextHref: string;
}>;

type ChatMessage = Readonly<{
  id: number;
  role: "assistant" | "user";
  content: string;
}>;

function guideForPath(pathname: string, subjectId: string | null): PageGuide {
  if (pathname.includes("/keywords")) {
    return {
      label: "关键词中心",
      description: "这里用于整理与主体相关的关键词，为后续生成问题库提供基础。",
      next: "关键词准备好后，下一步进入问题库生成用户可能向 AI 提出的真实问题。",
      nextHref: subjectId ? `/subjects/${subjectId}/questions` : "/subjects",
    };
  }
  if (pathname.includes("/questions")) {
    return {
      label: "问题库",
      description: "这里用于生成和管理用户可能向 AI 提出的真实问题。",
      next: "问题准备好后，就可以进入 AI 可见度检测。",
      nextHref: "/geo/detections",
    };
  }
  if (pathname.includes("/articles")) {
    return {
      label: "内容执行",
      description: "这里用于根据 GEO 优化策略生成和管理内容。",
      next: "内容优化完成后，可以进入复测验证查看前后变化。",
      nextHref: "/geo/retest",
    };
  }
  if (pathname.startsWith("/subjects")) {
    return {
      label: "主体档案",
      description: "这里用于建立和完善企业、品牌或产品的主体资料。",
      next: "主体资料保存后，下一步进入关键词中心。",
      nextHref: subjectId ? `/subjects/${subjectId}/keywords` : "/subjects",
    };
  }
  if (pathname.startsWith("/geo/detections")) {
    return {
      label: "AI 可见度检测",
      description: "这里用于检测问题在不同 AI 模型中的曝光、提及和引用情况。",
      next: "检测完成后，进入 GEO 报告与洞察查看结果。",
      nextHref: "/geo/reports",
    };
  }
  if (pathname.startsWith("/geo/strategy") || pathname.includes("/strategy")) {
    return {
      label: "优化策略",
      description: "这里用于根据检测和报告结果整理 GEO 优化方向。",
      next: "策略确认后，可以进入内容执行落实优化动作。",
      nextHref: subjectId ? `/subjects/${subjectId}/articles/new` : "/subjects",
    };
  }
  if (pathname.startsWith("/geo/retest")) {
    return {
      label: "复测验证",
      description: "这里用于在完成优化后重新检测，并比较前后变化。",
      next: "复测后可以继续针对没有改善的问题进入下一轮优化。",
      nextHref: "/geo/reports",
    };
  }
  if (pathname.startsWith("/geo/reports")) {
    return {
      label: "GEO 报告与洞察",
      description: "这里用于查看检测结果、品牌表现和需要优先处理的问题。",
      next: "看完报告后，下一步进入优化策略。",
      nextHref: "/geo/strategy",
    };
  }
  if (pathname.startsWith("/subscription")) {
    return {
      label: "套餐与额度",
      description: "这里用于查看当前套餐、可用功能和剩余额度。",
      next: "确认后可以返回 GEO 总览继续操作。",
      nextHref: "/workspace",
    };
  }
  return {
    label: "GEO 总览",
    description: "这里用于查看当前主体以及整个 GEO 优化流程的进度。",
    next: "从尚未完成的步骤继续；如果还没有主体，先建立主体档案。",
    nextHref: "/subjects",
  };
}

function localReply(question: string, guide: PageGuide): string {
  if (/下一步|接下来|然后/.test(question)) return `你现在在「${guide.label}」。${guide.next}`;
  if (/怎么|如何|干嘛|作用|功能/.test(question)) return guide.description;
  if (/为什么|不能|失败|不行|问题/.test(question)) {
    return `先检查「${guide.label}」所需的前置步骤是否已经完成。${guide.next}`;
  }
  return `你现在在「${guide.label}」。${guide.description} ${guide.next}`;
}

export function UserAssistantWidget() {
  const pathname = usePathname();
  const { active, currentSubject } = useSubjectWorkspace();
  const subjectId = currentSubject?.id ?? null;
  const guide = useMemo(() => guideForPath(pathname, subjectId), [pathname, subjectId]);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [sequence, setSequence] = useState(2);
  const [messages, setMessages] = useState<ChatMessage[]>([
    { id: 1, role: "assistant", content: "需要我帮你看看当前这一步怎么做吗？" },
  ]);

  const ask = (question: string) => {
    const value = question.trim();
    if (!value) return;
    const userId = sequence;
    const assistantId = sequence + 1;
    setMessages((current) => [
      ...current,
      { id: userId, role: "user", content: value },
      { id: assistantId, role: "assistant", content: localReply(value, guide) },
    ]);
    setSequence((current) => current + 2);
    setDraft("");
  };

  if (!active) return null;

  return (
    <div className="xw-assistant" aria-live="polite">
      {open && (
        <section className="xw-assistant__panel" aria-label="显问 AI 助手">
          <header className="xw-assistant__header">
            <div className="xw-assistant__identity">
              <img
                className="xw-assistant__brand-logo"
                src={assistantMascotSrc}
                alt="显问 AI"
              />
              <div>
                <Typography.Text strong>显问 AI 助手</Typography.Text>
                <Typography.Text type="secondary">当前：{guide.label}</Typography.Text>
              </div>
            </div>
            <Button
              type="text"
              shape="circle"
              aria-label="收起显问 AI 助手"
              icon={<CloseOutlined />}
              onClick={() => setOpen(false)}
            />
          </header>

          <div className="xw-assistant__body">
            {messages.map((message) => (
              <div
                key={message.id}
                className={`xw-assistant__message xw-assistant__message--${message.role}`}
              >
                {message.content}
              </div>
            ))}

            <div className="xw-assistant__suggestions">
              <Button size="small" onClick={() => ask("我下一步该做什么？")}>下一步该做什么？</Button>
              <Button size="small" onClick={() => ask("这个功能怎么用？")}>这个功能怎么用？</Button>
              <Button size="small" onClick={() => ask("为什么现在不能继续？")}>为什么不能继续？</Button>
            </div>

            <Button className="xw-assistant__next" href={guide.nextHref} type="link">
              前往相关步骤
            </Button>
          </div>

          <footer className="xw-assistant__composer">
            <Input.TextArea
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder="输入你遇到的问题…"
              autoSize={{ minRows: 1, maxRows: 4 }}
              onPressEnter={(event) => {
                if (!event.shiftKey) {
                  event.preventDefault();
                  ask(draft);
                }
              }}
            />
            <Button
              type="primary"
              shape="circle"
              aria-label="发送问题"
              icon={<SendOutlined />}
              disabled={!draft.trim()}
              onClick={() => ask(draft)}
            />
          </footer>
        </section>
      )}

      <Button
        className={`xw-assistant__launcher${open ? " xw-assistant__launcher--open" : ""}`}
        shape="circle"
        aria-label={open ? "显问 AI 助手已展开" : "打开显问 AI 助手"}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="xw-assistant__launcher-crop" aria-hidden="true">
          <img src={assistantLogoSrc} alt="" />
        </span>
      </Button>
    </div>
  );
}
