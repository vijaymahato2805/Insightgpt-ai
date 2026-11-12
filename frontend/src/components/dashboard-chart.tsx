import { useMemo } from "react";
import * as echarts from "echarts/core";
import { BarChart, LineChart, PieChart } from "echarts/charts";
import { GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import ReactECharts from "echarts-for-react/lib/core";
import type { EChartsOption } from "echarts";
import type { DashboardWidget } from "@/types/dashboard";

echarts.use([BarChart, LineChart, PieChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer]);

export function ChartCard({
  widget,
  rows,
  onDrillDown,
}: {
  widget: DashboardWidget;
  rows: Array<Record<string, unknown>>;
  onDrillDown: (field: string, value: string) => void;
}) {
  const option = useMemo(() => createChartOption(widget, rows), [widget, rows]);
  const categories = useMemo(
    () => unique(rows.map((row) => stringify(widget.category_field ? row[widget.category_field] : ""))),
    [widget.category_field, rows],
  );
  const onEvents = useMemo(() => ({
    click: (event: { name?: string; dataIndex?: number }) => {
      if (!widget.drilldown_field) return;
      const selected = widget.visualization === "pie" || widget.visualization === "donut"
        ? event.name
        : (typeof event.dataIndex === "number" ? categories[event.dataIndex] : undefined);
      if (selected === undefined) return;
      const sourceRow = rows.find((row) => stringify(row[widget.category_field ?? ""]) === selected);
      const value = sourceRow ? stringify(sourceRow[widget.drilldown_field]) : selected;
      if (value && value !== "—") onDrillDown(widget.drilldown_field, value);
    },
  }), [categories, onDrillDown, rows, widget.category_field, widget.drilldown_field, widget.visualization]);

  if (rows.length === 0) return <EmptyState />;
  if (!widget.category_field || !widget.value_field) return <EmptyState message="This result has no chartable category and value fields." />;
  return (
    <div>
      {widget.drilldown_field && <p className="mb-1 text-[10px] text-slate-600">Select a data point to filter the dashboard.</p>}
      <ReactECharts
        echarts={echarts}
        option={option}
        onEvents={onEvents}
        notMerge
        lazyUpdate
        opts={{ renderer: "canvas" }}
        style={{ height: 280, width: "100%" }}
      />
    </div>
  );
}

function createChartOption(widget: DashboardWidget, rows: Array<Record<string, unknown>>): EChartsOption {
  const categoryField = widget.category_field ?? "";
  const valueField = widget.value_field ?? "";
  const categories = unique(rows.map((row) => stringify(row[categoryField])));
  const groups = widget.series_field
    ? unique(rows.map((row) => stringify(row[widget.series_field!])))
    : [valueField || "Value"];
  const valuesByGroup = groups.map((group) => {
    const totals = new Map<string, number>();
    rows.forEach((row) => {
      if (widget.series_field && stringify(row[widget.series_field]) !== group) return;
      const category = stringify(row[categoryField]);
      const value = numericValue(row[valueField]);
      if (value !== null) totals.set(category, (totals.get(category) ?? 0) + value);
    });
    return { name: group, data: categories.map((category) => totals.get(category) ?? null) };
  });

  if (widget.visualization === "pie" || widget.visualization === "donut") {
    const totalByCategory = new Map<string, number>();
    rows.forEach((row) => {
      const category = stringify(row[categoryField]);
      const value = numericValue(row[valueField]);
      if (value !== null) totalByCategory.set(category, (totalByCategory.get(category) ?? 0) + value);
    });
    return baseOption({
      tooltip: { trigger: "item", formatter: "{b}<br/>{c} ({d}%)" },
      legend: { bottom: 0, type: "scroll", textStyle: { color: "#8b8d9c", fontSize: 10 } },
      series: [{
        name: valueField,
        type: "pie",
        radius: widget.visualization === "donut" ? ["48%", "72%"] : "72%",
        center: ["50%", "46%"],
        data: categories.flatMap((name) => {
          const value = totalByCategory.get(name);
          return value === undefined ? [] : [{ name, value }];
        }),
        label: { color: "#b9bac5", fontSize: 10 },
        itemStyle: { borderColor: "#11131c", borderWidth: 2, borderRadius: 4 },
      }],
    });
  }

  const lineLike = widget.visualization === "line" || widget.visualization === "area";
  return baseOption({
    tooltip: { trigger: "axis" },
    legend: groups.length > 1 ? { top: 0, textStyle: { color: "#8b8d9c", fontSize: 10 } } : undefined,
    grid: { left: 12, right: 12, top: groups.length > 1 ? 38 : 18, bottom: 38, containLabel: true },
    xAxis: { type: "category", data: categories, axisLabel: { color: "#797b8c", fontSize: 9, hideOverlap: true }, axisLine: { lineStyle: { color: "#2c2e3a" } }, axisTick: { show: false } },
    yAxis: { type: "value", name: valueField, nameTextStyle: { color: "#696b7a", fontSize: 9 }, axisLabel: { color: "#797b8c", fontSize: 9 }, splitLine: { lineStyle: { color: "#252733" } } },
    series: valuesByGroup.map((series, index) => ({
      ...series,
      type: lineLike ? "line" : "bar",
      smooth: lineLike,
      showSymbol: lineLike && categories.length < 30,
      symbolSize: 6,
      barMaxWidth: 32,
      areaStyle: widget.visualization === "area" ? { opacity: 0.16 } : undefined,
      emphasis: { focus: "series" },
      itemStyle: { color: chartColors[index % chartColors.length], borderRadius: lineLike ? 0 : [4, 4, 0, 0] },
      lineStyle: { width: 2.5 },
    })),
  });
}

const chartColors = ["#a78bfa", "#38bdf8", "#34d399", "#fbbf24", "#fb7185", "#818cf8"];

function baseOption(option: EChartsOption): EChartsOption {
  return {
    animationDuration: 360,
    textStyle: { fontFamily: "DM Sans, sans-serif" },
    color: chartColors,
    ...option,
  };
}

function EmptyState({ message = "No rows for the current filters." }: { message?: string }) {
  return <div className="flex min-h-[150px] items-center justify-center rounded-xl border border-dashed border-white/[.07] px-5 text-center text-xs text-slate-600">{message}</div>;
}

function numericValue(value: unknown): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value !== "string") return null;
  const parsed = Number(value.replaceAll(",", ""));
  return Number.isFinite(parsed) ? parsed : null;
}

function stringify(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

function unique(values: string[]): string[] {
  return [...new Set(values.filter((value) => value !== "—"))];
}
