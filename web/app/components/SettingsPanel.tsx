"use client";

import { useId } from "react";

import { VLM_MODEL_OPTIONS, type JobSettings, type VlmModelId } from "@/lib/types";

export type { JobSettings };

export const DEFAULT_SETTINGS: JobSettings = {
  fps: 2.0,
  max_frames: 400,
  target_long_side: 1920,
  segment: true,
  keyframes: 5,
  vlm_model: "claude-haiku-4-5",
};

interface Props {
  value: JobSettings;
  onChange: (next: JobSettings) => void;
  durationS?: number;
}

export function SettingsPanel({ value, onChange, durationS }: Props) {
  const set = <K extends keyof JobSettings>(k: K, v: JobSettings[K]) =>
    onChange({ ...value, [k]: v });

  const projectedFrames = durationS
    ? Math.min(Math.ceil(durationS * value.fps), value.max_frames)
    : null;

  return (
    <div className="flex flex-col gap-4 rounded-xl border border-ink-800 bg-ink-900/60 p-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold tracking-tight">Pipeline settings</h2>
        {projectedFrames != null && (
          <span className="font-mono text-[10px] uppercase tracking-wider text-ink-500">
            ≈ {projectedFrames} frames
          </span>
        )}
      </div>

      <Slider
        label="Frames per second"
        suffix="fps"
        min={0.5}
        max={10}
        step={0.5}
        value={value.fps}
        onChange={(v) => set("fps", v)}
      />
      <Slider
        label="Max frames total"
        min={50}
        max={800}
        step={10}
        value={value.max_frames}
        onChange={(v) => set("max_frames", v)}
      />
      <Slider
        label="Target long side"
        suffix="px"
        min={720}
        max={3840}
        step={20}
        value={value.target_long_side}
        onChange={(v) => set("target_long_side", v)}
      />

      <Field label="Run segmentation after splat">
        <button
          type="button"
          onClick={() => set("segment", !value.segment)}
          className={`flex w-full items-center justify-between rounded-md border px-3 py-1.5 font-mono text-[11px] uppercase tracking-wider transition ${
            value.segment
              ? "border-accent-400/60 bg-accent-500/15 text-accent-200"
              : "border-ink-700 bg-ink-900 text-ink-400"
          }`}
        >
          <span>{value.segment ? "enabled" : "disabled"}</span>
          <span>{value.segment ? "✓" : "—"}</span>
        </button>
      </Field>

      {value.segment && (
        <Slider
          label="Segmentation keyframes"
          min={2}
          max={20}
          step={1}
          value={value.keyframes}
          onChange={(v) => set("keyframes", v)}
        />
      )}

      {value.segment && (
        <Field label="VLM (routed through Pydantic AI Gateway)">
          <div className="flex flex-col gap-1">
            {VLM_MODEL_OPTIONS.map((opt) => {
              const active = (value.vlm_model ?? "claude-haiku-4-5") === opt.id;
              return (
                <button
                  key={opt.id}
                  type="button"
                  onClick={() => set("vlm_model", opt.id as VlmModelId)}
                  className={`flex items-center justify-between rounded-md border px-3 py-1.5 font-mono text-[11px] transition ${
                    active
                      ? "border-accent-400/60 bg-accent-500/15 text-accent-200"
                      : "border-ink-700 bg-ink-900 text-ink-400 hover:border-ink-600"
                  }`}
                >
                  <span className="uppercase tracking-wider">{opt.label}</span>
                  <span className="text-[10px] text-ink-500">{opt.cost}</span>
                </button>
              );
            })}
          </div>
        </Field>
      )}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="font-mono text-[10px] uppercase tracking-wider text-ink-500">
        {label}
      </span>
      {children}
    </label>
  );
}

function Slider({
  label,
  min,
  max,
  step,
  value,
  onChange,
  suffix,
}: {
  label: string;
  min: number;
  max: number;
  step: number;
  value: number;
  onChange: (v: number) => void;
  suffix?: string;
}) {
  const id = useId();
  return (
    <label htmlFor={id} className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between">
        <span className="font-mono text-[10px] uppercase tracking-wider text-ink-500">
          {label}
        </span>
        <span className="font-mono text-[11px] tabular-nums text-ink-200">
          {value}
          {suffix ? ` ${suffix}` : ""}
        </span>
      </div>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="accent-accent-400"
      />
    </label>
  );
}
