import { FormEvent, useEffect, useMemo, useState } from "react";
import DatePicker, { DateObject } from "react-multi-date-picker";
import gregorian from "react-date-object/calendars/gregorian";
import persian from "react-date-object/calendars/persian";
import gregorian_en from "react-date-object/locales/gregorian_en";
import persian_fa from "react-date-object/locales/persian_fa";
import { api } from "./api";
import type { AlertRecord, Location } from "./types";

type CalendarMode = "jalali" | "gregorian";

function isoToday(): string {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function DateField({
  value,
  onChange,
  mode,
  label
}: {
  value: string;
  onChange: (value: string) => void;
  mode: CalendarMode;
  label: string;
}) {
  const calendar = mode === "jalali" ? persian : gregorian;
  const locale = mode === "jalali" ? persian_fa : gregorian_en;
  const displayed = new DateObject({ date: value, format: "YYYY-MM-DD", calendar: gregorian })
    .convert(calendar);
  const minimum = new DateObject({ date: isoToday(), format: "YYYY-MM-DD", calendar: gregorian })
    .convert(calendar);

  return (
    <label className="field">
      <span>{label}</span>
      <DatePicker
        value={displayed}
        minDate={minimum}
        calendar={calendar}
        locale={locale}
        calendarPosition="bottom-right"
        inputClass="date-input"
        format="YYYY/MM/DD"
        onChange={(next) => {
          if (next instanceof DateObject) {
            onChange(new DateObject(next).convert(gregorian).format("YYYY-MM-DD"));
          }
        }}
      />
    </label>
  );
}

function LocationField({
  label,
  value,
  onChange,
  locations
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  locations: Location[];
}) {
  return (
    <label className="field">
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)} required>
        <option value="">انتخاب شهر یا فرودگاه</option>
        {locations.map((location) => (
          <option key={location.code} value={location.code}>
            {location.city_fa} — {location.airport_fa} ({location.code})
          </option>
        ))}
      </select>
    </label>
  );
}

const statusLabel: Record<AlertRecord["status"], string> = {
  active: "فعال",
  cancelled: "لغوشده",
  expired: "پایان‌یافته"
};

export default function App() {
  const today = useMemo(isoToday, []);
  const [locations, setLocations] = useState<Location[]>([]);
  const [alerts, setAlerts] = useState<AlertRecord[]>([]);
  const [calendarMode, setCalendarMode] = useState<CalendarMode>("jalali");
  const [tripType, setTripType] = useState<"one_way" | "round_trip">("one_way");
  const [origin, setOrigin] = useState("");
  const [destination, setDestination] = useState("");
  const [flexible, setFlexible] = useState(false);
  const [outboundStart, setOutboundStart] = useState(today);
  const [outboundEnd, setOutboundEnd] = useState(today);
  const [outboundTimeStart, setOutboundTimeStart] = useState("00:00");
  const [outboundTimeEnd, setOutboundTimeEnd] = useState("23:59");
  const [returnStart, setReturnStart] = useState(today);
  const [returnEnd, setReturnEnd] = useState(today);
  const [returnTimeStart, setReturnTimeStart] = useState("00:00");
  const [returnTimeEnd, setReturnTimeEnd] = useState("23:59");
  const [adults, setAdults] = useState(1);
  const [children, setChildren] = useState(0);
  const [infants, setInfants] = useState(0);
  const [cabin, setCabin] = useState<"economy" | "business">("economy");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  async function refreshAlerts() {
    setAlerts(await api.alerts());
  }

  useEffect(() => {
    Promise.all([api.session(), api.locations(), api.alerts()])
      .then(([, locationValues, alertValues]) => {
        setLocations(locationValues);
        setAlerts(alertValues);
      })
      .catch((reason: Error) => setError(reason.message))
      .finally(() => setLoading(false));
  }, []);

  function updateOutboundStart(value: string) {
    setOutboundStart(value);
    if (!flexible || outboundEnd < value) setOutboundEnd(value);
    if (returnStart < value) {
      setReturnStart(value);
      setReturnEnd(value);
    }
  }

  function toggleFlexible(value: boolean) {
    setFlexible(value);
    if (!value) {
      setOutboundEnd(outboundStart);
      setReturnEnd(returnStart);
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setSuccess("");
    if (origin === destination) {
      setError("مبدأ و مقصد باید متفاوت باشند.");
      return;
    }
    setSubmitting(true);
    const criteria = {
      trip_type: tripType,
      origin,
      destination,
      outbound_dates: { start: outboundStart, end: flexible ? outboundEnd : outboundStart },
      outbound_times: { start: outboundTimeStart, end: outboundTimeEnd },
      return_dates:
        tripType === "round_trip"
          ? { start: returnStart, end: flexible ? returnEnd : returnStart }
          : null,
      return_times:
        tripType === "round_trip"
          ? { start: returnTimeStart, end: returnTimeEnd }
          : null,
      passengers: { adults, children, infants },
      cabin,
      timezone: "Asia/Tehran"
    };
    try {
      await api.createAlert(criteria);
      await refreshAlerts();
      setSuccess("پایش ساخته شد. نتیجه اولیه و تغییرات بعدی در ربات ارسال می‌شود.");
      window.Telegram?.WebApp.HapticFeedback?.notificationOccurred("success");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "ثبت پایش ناموفق بود.");
      window.Telegram?.WebApp.HapticFeedback?.notificationOccurred("error");
    } finally {
      setSubmitting(false);
    }
  }

  async function cancelAlert(id: string) {
    try {
      await api.cancelAlert(id);
      await refreshAlerts();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "لغو پایش ناموفق بود.");
    }
  }

  if (loading) {
    return <main className="shell loading">در حال آماده‌سازی فرم…</main>;
  }

  return (
    <main className="shell">
      <header className="hero">
        <div className="plane-mark" aria-hidden="true">✦</div>
        <div>
          <p className="eyebrow">دستیار هوشمند سفر</p>
          <h1>پایش پرواز</h1>
          <p>چهار سایت معتبر را هم‌زمان بررسی می‌کنیم و فقط تغییرات واقعی را خبر می‌دهیم.</p>
        </div>
      </header>

      {error && <div className="notice error" role="alert">{error}</div>}
      {success && <div className="notice success" role="status">{success}</div>}

      <form className="card form-card" onSubmit={submit}>
        <div className="segmented" aria-label="نوع سفر">
          <button type="button" className={tripType === "one_way" ? "selected" : ""} onClick={() => setTripType("one_way")}>یک‌طرفه</button>
          <button type="button" className={tripType === "round_trip" ? "selected" : ""} onClick={() => setTripType("round_trip")}>رفت‌وبرگشت</button>
        </div>

        <section className="grid two">
          <LocationField label="مبدأ" value={origin} onChange={setOrigin} locations={locations} />
          <LocationField label="مقصد" value={destination} onChange={setDestination} locations={locations} />
        </section>

        <div className="section-heading">
          <h2>تاریخ و ساعت رفت</h2>
          <button type="button" className="calendar-toggle" onClick={() => setCalendarMode(calendarMode === "jalali" ? "gregorian" : "jalali")}>
            {calendarMode === "jalali" ? "نمایش میلادی" : "نمایش شمسی"}
          </button>
        </div>
        <label className="toggle-row">
          <input type="checkbox" checked={flexible} onChange={(event) => toggleFlexible(event.target.checked)} />
          <span>تاریخ سفر منعطف است</span>
        </label>
        <section className="grid two">
          <DateField label={flexible ? "از تاریخ" : "تاریخ رفت"} value={outboundStart} onChange={updateOutboundStart} mode={calendarMode} />
          {flexible && <DateField label="تا تاریخ" value={outboundEnd} onChange={setOutboundEnd} mode={calendarMode} />}
          <label className="field"><span>از ساعت</span><input type="time" value={outboundTimeStart} onChange={(e) => setOutboundTimeStart(e.target.value)} /></label>
          <label className="field"><span>تا ساعت</span><input type="time" value={outboundTimeEnd} onChange={(e) => setOutboundTimeEnd(e.target.value)} /></label>
        </section>

        {tripType === "round_trip" && (
          <>
            <div className="section-heading"><h2>تاریخ و ساعت برگشت</h2></div>
            <section className="grid two">
              <DateField label={flexible ? "از تاریخ" : "تاریخ برگشت"} value={returnStart} onChange={(value) => { setReturnStart(value); if (!flexible || returnEnd < value) setReturnEnd(value); }} mode={calendarMode} />
              {flexible && <DateField label="تا تاریخ" value={returnEnd} onChange={setReturnEnd} mode={calendarMode} />}
              <label className="field"><span>از ساعت</span><input type="time" value={returnTimeStart} onChange={(e) => setReturnTimeStart(e.target.value)} /></label>
              <label className="field"><span>تا ساعت</span><input type="time" value={returnTimeEnd} onChange={(e) => setReturnTimeEnd(e.target.value)} /></label>
            </section>
          </>
        )}

        <div className="section-heading"><h2>مسافران و کلاس</h2></div>
        <section className="grid passengers">
          <label className="field"><span>بزرگسال</span><input type="number" min="1" max="9" value={adults} onChange={(e) => setAdults(Number(e.target.value))} /></label>
          <label className="field"><span>کودک</span><input type="number" min="0" max="8" value={children} onChange={(e) => setChildren(Number(e.target.value))} /></label>
          <label className="field"><span>نوزاد</span><input type="number" min="0" max={adults} value={infants} onChange={(e) => setInfants(Number(e.target.value))} /></label>
          <label className="field"><span>کلاس پرواز</span><select value={cabin} onChange={(e) => setCabin(e.target.value as "economy" | "business")}><option value="economy">اکونومی</option><option value="business">بیزینس</option></select></label>
        </section>

        <button className="primary" type="submit" disabled={submitting || !origin || !destination}>
          {submitting ? "در حال ثبت…" : "شروع پایش پرواز"}
        </button>
        <p className="fine-print">قیمت و موجودی نهایی را پیش از خرید در سایت فروشنده تأیید کنید.</p>
      </form>

      <section className="card alerts-card">
        <div className="section-heading"><h2>پایش‌های من</h2><span className="counter">{alerts.filter((item) => item.status === "active").length} فعال</span></div>
        {alerts.length === 0 ? <p className="empty">هنوز پایشی نساخته‌اید.</p> : alerts.map((alert) => (
          <article className="alert-row" key={alert.id}>
            <div><strong>{alert.criteria.origin} ← {alert.criteria.destination}</strong><small>{alert.criteria.outbound_dates.start} تا {alert.criteria.outbound_dates.end}</small></div>
            <div className="alert-actions"><span className={`status ${alert.status}`}>{statusLabel[alert.status]}</span>{alert.status === "active" && <button type="button" onClick={() => cancelAlert(alert.id)}>لغو</button>}</div>
          </article>
        ))}
      </section>
    </main>
  );
}

