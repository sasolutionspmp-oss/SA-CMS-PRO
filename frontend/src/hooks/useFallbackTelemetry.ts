import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { fetchIntakeTelemetry, type IntakeTelemetry } from "../api";

const DEFAULT_TELEMETRY: IntakeTelemetry = {
  fallback_events: 0,
  last_event_at: null,
};

export function useFallbackTelemetry(pollIntervalMs = 30000): IntakeTelemetry {
  const [telemetry, setTelemetry] = useState<IntakeTelemetry>(DEFAULT_TELEMETRY);
  const lastCountRef = useRef(0);
  const lastTimestampRef = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const execute = async () => {
      try {
        const payload = await fetchIntakeTelemetry();
        if (!cancelled) {
          setTelemetry(payload);
        }
      } catch (error) {
        if (!cancelled) {
          console.debug("intake telemetry poll failed", error);
        }
      }
    };

    execute();
    const handle = window.setInterval(execute, pollIntervalMs);
    return () => {
      cancelled = true;
      window.clearInterval(handle);
    };
  }, [pollIntervalMs]);

  useEffect(() => {
    const { fallback_events: count, last_event_at: lastEvent } = telemetry;
    const previousCount = lastCountRef.current;
    const previousTimestamp = lastTimestampRef.current;

    if (count <= 0) {
      lastCountRef.current = 0;
      lastTimestampRef.current = lastEvent ?? null;
      return;
    }

    const hasNewCount = count > previousCount;
    const hasNewTimestamp = Boolean(lastEvent) && lastEvent !== previousTimestamp;

    if (hasNewCount || hasNewTimestamp) {
      let description = `${count} fallback event${count === 1 ? "" : "s"}.`;
      if (lastEvent) {
        const parsed = new Date(lastEvent);
        if (!Number.isNaN(parsed.getTime())) {
          description = `${count} fallback event${count === 1 ? "" : "s"} (last at ${parsed.toLocaleString()}).`;
        }
      }
      toast.warning("Fallback resilience active", {
        description,
        duration: 6000,
      });
    }

    lastCountRef.current = count;
    lastTimestampRef.current = lastEvent ?? null;
  }, [telemetry.fallback_events, telemetry.last_event_at]);

  return telemetry;
}
