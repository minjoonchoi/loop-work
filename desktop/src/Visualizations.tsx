import { useEffect, useRef } from "react";
import * as echarts from "echarts";
import {
  ReactFlow,
  Background,
  Controls,
  Position,
  type Node,
  type Edge,
} from "@xyflow/react";
import { useRive, RuntimeLoader } from "@rive-app/react-canvas";
import { useLiveReducedMotion } from "./useReduced";
import { states, type Row } from "./types";
import "@xyflow/react/dist/style.css";
import { runtimeAsset } from "./runtimeAsset";
import wasmURL from "@rive-app/canvas/rive.wasm?url";
RuntimeLoader.setWasmUrl(wasmURL);
export function StatusChart({ tasks }: { tasks: Row[] }) {
  const el = useRef<HTMLDivElement>(null);
  const reduced = useLiveReducedMotion();
  useEffect(() => {
    if (!el.current) return;
    const chart = echarts.init(el.current);
    const css = getComputedStyle(el.current);
    const token = (name: string, fallback: string) =>
      css.getPropertyValue(name).trim() || fallback;
    const muted = token("--lw-muted", "#64748b");
    const foreground = token("--lw-text", "#1e293b");
    const border = token("--lw-border", "#e2e8f0");
    const fallbackPalette = [
      "#5f6d80",
      "#305fc6",
      "#9a6000",
      "#147d64",
      "#aa473f",
    ];
    const palette = states.map(([state], index) =>
      token("--lw-state-" + state, fallbackPalette[index]),
    );
    chart.setOption({
      backgroundColor: "transparent",
      textStyle: {
        fontFamily: css.fontFamily,
        color: foreground,
      },
      animation: !reduced,
      aria: {
        enabled: true,
        label: {
          description:
            "현재 프로젝트 작업의 준비·진행·사용자 확인·완료·중단 상태별 실제 개수입니다. 아래 표에서 같은 수치를 확인할 수 있습니다.",
        },
      },
      tooltip: {
        trigger: "axis",
        confine: true,
        backgroundColor: token("--lw-surface", "#ffffff"),
        borderColor: border,
        borderWidth: 1,
        padding: [10, 12],
        textStyle: { color: foreground, fontSize: 12 },
        axisPointer: {
          type: "shadow",
          shadowStyle: { color: token("--lw-accent-soft", "#e8f5ef") },
        },
        valueFormatter: (value: unknown) => String(value) + "개",
        extraCssText: "border-radius:10px;box-shadow:0 8px 24px #0f172a12;",
      },
      grid: { left: 84, right: 40, top: 10, bottom: 26 },
      xAxis: {
        type: "value",
        minInterval: 1,
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { color: muted, fontSize: 11 },
        splitLine: { lineStyle: { color: border, type: "dashed" } },
      },
      yAxis: {
        type: "category",
        inverse: true,
        data: states.map((x) => x[1]),
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { color: foreground, fontSize: 12, margin: 14 },
      },
      series: [
        {
          type: "bar",
          barWidth: 16,
          data: states.map(([s, name], index) => ({
            name,
            value: tasks.filter((t) => t.board_state === s).length,
            itemStyle: { color: palette[index] },
          })),
          itemStyle: { borderRadius: [0, 4, 4, 0] },
          label: {
            show: true,
            position: "right",
            formatter: "{c}개",
            color: foreground,
            fontSize: 11,
            fontWeight: 600,
          },
          emphasis: { focus: "self" },
        },
      ],
    });
    const resize = new ResizeObserver(() => chart.resize());
    resize.observe(el.current);
    return () => {
      resize.disconnect();
      chart.dispose();
    };
  }, [tasks, reduced]);
  return (
    <section className="visualization-panel">
      <h3>현재 작업 상태</h3>
      <div
        ref={el}
        style={{ height: 210 }}
        role="img"
        aria-label="실제 작업 상태 집계"
      />
      <p className="muted visualization-caption">
        현재 목록 {tasks.length}개 기준
      </p>
      <table className="sr-only">
        <caption>실제 작업 상태별 수량</caption>
        <tbody>
          {states.map(([s, label]) => (
            <tr key={s}>
              <th scope="row">{label}</th>
              <td>{tasks.filter((t) => t.board_state === s).length}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
export function AuditFlow({ task }: { task: Row }) {
  const items = [
    { id: task.id, label: task.state_label || "상태 확인 필요" },
    ...(task.documents || []).map((d, i) => ({
      id: "doc-" + i,
      label: d.path.split("/").at(-1) || d.path,
    })),
    ...(task.requests || []).map((r) => ({
      id: "request-" + r.id,
      label:
        r.record.title +
        " · " +
        (
          {
            pending: "답변 필요",
            answered: "답변 기록",
            declined: "거절됨",
            executed: "실행됨",
            failed: "실행 실패",
          } as Record<string, string>
        )[r.record.status],
    })),
  ];
  const nodes: Node[] = items.map((x, i) => ({
    id: x.id,
    position: { x: i ? 316 : 0, y: i ? 98 * (i - 1) : 30 },
    data: { label: x.label },
    ariaLabel: x.label,
    sourcePosition: Position.Right,
    targetPosition: Position.Left,
    style: {
      width: 224,
      minHeight: 54,
      padding: "12px 14px",
      borderRadius: 10,
      border: i
        ? "1px solid var(--lw-border, #e2e8f0)"
        : "1px solid var(--lw-accent, #147d64)",
      background: i
        ? "var(--lw-surface, #ffffff)"
        : "var(--lw-accent-soft, #e8f5ef)",
      color: "var(--lw-text, #1e293b)",
      boxShadow: "0 2px 6px #0f172a06",
      fontFamily: "inherit",
      fontSize: 12,
      fontWeight: i ? 500 : 650,
      lineHeight: 1.6,
      overflowWrap: "anywhere",
    },
  }));
  const edges: Edge[] = items.slice(1).map((x) => ({
    id: task.id + "-" + x.id,
    source: task.id,
    target: x.id,
    type: "smoothstep",
    style: { stroke: "var(--lw-muted, #64748b)", strokeWidth: 1.25 },
  }));
  return (
    <section className="visualization-panel">
      <h3>실제 기록 연결</h3>
      <p className="muted visualization-caption">
        확인된 문서·요청 관계만 표시합니다. 자동 실행 계획이 아닙니다.
      </p>
      <div className="audit-flow-surface" style={{ height: 340 }}>
        <ReactFlow
          ariaLabelConfig={{
            "controls.zoomIn.ariaLabel": "확대",
            "controls.zoomOut.ariaLabel": "축소",
            "controls.fitView.ariaLabel": "전체 기록 보기",
            "node.a11yDescription.default": "읽기 전용 근거 노드",
          }}
          nodes={nodes}
          edges={edges}
          nodesDraggable={false}
          nodesConnectable={false}
          edgesFocusable={false}
          deleteKeyCode={null}
          fitView
          fitViewOptions={{ padding: 0.22 }}
          style={{ background: "var(--lw-surface-muted, #f7f8fa)" }}
        >
          <Background color="var(--lw-border, #e2e8f0)" gap={20} size={1} />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
    </section>
  );
}
export function RuntimeIndicator({
  paused,
  connected,
}: {
  paused: boolean;
  connected: boolean;
}) {
  const reduced = useLiveReducedMotion();
  const { rive, RiveComponent } = useRive({
    buffer: runtimeAsset,
    artboard: "New Artboard",
    animations: "Animation 1",
    autoplay: !reduced,
  });
  useEffect(() => {
    if (reduced) rive?.pause();
    else if (connected && !paused) rive?.play("Animation 1");
    else rive?.pause();
  }, [rive, paused, connected, reduced]);
  const status = !connected
    ? "연결 확인 필요"
    : paused
      ? "일시정지 기록"
      : "연결됨";
  return (
    <div
      className="runtime-indicator"
      role="status"
      aria-live="polite"
      aria-atomic="true"
      aria-label={
        "하네스 연결 상태: " + status + (reduced ? ", 동작 줄임 사용" : "")
      }
      data-connected={connected}
      data-rive-ready={!!rive}
      data-rive-animations={rive?.animationNames.join("|")}
      data-paused={paused}
      data-reduced-motion={!!reduced}
    >
      <div className="runtime-canvas" style={{ width: 22, height: 22 }}>
        <RiveComponent aria-label="실제 연결 상태 애니메이션" />
      </div>
      <span className="runtime-copy">{status}</span>
      {reduced && <span className="runtime-motion-note">동작 줄임</span>}
    </div>
  );
}
