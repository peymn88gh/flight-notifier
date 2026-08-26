import { FormEvent, useEffect, useMemo, useState } from "react";
import DatePicker, { DateObject } from "react-multi-date-picker";
import gregorian from "react-date-object/calendars/gregorian";
import persian from "react-date-object/calendars/persian";
import gregorian_en from "react-date-object/locales/gregorian_en";
import persian_fa from "react-date-object/locales/persian_fa";
import { api, ApiError } from "./api";
import type { AlertRecord, HotelAlertRecord, HotelDestination, Location } from "./types";

type CalendarMode = "jalali" | "gregorian";

function isoToday(): string {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function toAsciiDigits(value: string): string {
  return value
    .replace(/[\u06f0-\u06f9]/g, (digit) => String(digit.charCodeAt(0) - 0x06f0))
    .replace(/[\u0660-\u0669]/g, (digit) => String(digit.charCodeAt(0) - 0x0660));
}

function PlaneIcon({ className = "" }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 64 64"
      fill="none"
      aria-hidden="true"
    >
      <path
        d="M56.7 28.3 38.9 18.1 35.8 7.4c-.5-1.8-2.1-3.1-4-3.1s-3.5 1.3-4 3.1l-3.1 10.7L6.9 28.3c-1.5.9-2.4 2.5-2.4 4.2 0 2.8 2.3 5 5 5h17.1l-1.8 13.3-6.1 4.2v4.7l13.1-3.1 13.1 3.1V55l-6.1-4.2L37 37.5h17.1c2.8 0 5-2.2 5-5 0-1.7-.9-3.3-2.4-4.2Z"
        fill="currentColor"
      />
    </svg>
  );
}

function PlaneLoader({ compact = false }: { compact?: boolean }) {
  return (
    <span
      className={"plane-loader" + (compact ? " compact" : "")}
      role="status"
      aria-label="در حال بارگذاری"
    >
      <span className="plane-orbit">
        <PlaneIcon />
      </span>
      <span className="sr-only">در حال بارگذاری</span>
    </span>
  );
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
  const displayed = new DateObject({
    date: toAsciiDigits(value),
    format: "YYYY-MM-DD",
    calendar: gregorian
  })
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
          if (!next || Array.isArray(next)) return;

          const selected = new DateObject({
            date: next.toDate(),
            calendar: gregorian,
            locale: gregorian_en
          });
          onChange(toAsciiDigits(selected.format("YYYY-MM-DD")));
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

function HotelDestinationField({
  label,
  value,
  onChange,
  destinations
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  destinations: HotelDestination[];
}) {
  return (
    <label className="field">
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)} required>
        <option value="">انتخاب شهر</option>
        {destinations.map((destination) => (
          <option key={destination.code} value={destination.code}>
            {destination.city_fa} — {destination.country_fa}
          </option>
        ))}
      </select>
    </label>
  );
}

function StepperField({
  label,
  value,
  onChange,
  min,
  max
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
  min: number;
  max: number;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      <div className="stepper">
        <button type="button" onClick={() => onChange(Math.max(min, value - 1))} disabled={value <= min}>
          −
        </button>
        <span>{value}</span>
        <button type="button" onClick={() => onChange(Math.min(max, value + 1))} disabled={value >= max}>
          +
        </button>
      </div>
    </label>
  );
}

export default function App() {
  const today = useMemo(isoToday, []);
  const [activeTab, setActiveTab] = useState<"flight" | "hotel">("flight");
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
  const [maxActiveAlerts, setMaxActiveAlerts] = useState(2);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [limitDialogOpen, setLimitDialogOpen] = useState(false);
  const [archivingId, setArchivingId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const [hotelDestinations, setHotelDestinations] = useState<HotelDestination[]>([]);
  const [hotelAlerts, setHotelAlerts] = useState<HotelAlertRecord[]>([]);
  const [hotelDestination, setHotelDestination] = useState("");
  const [hotelFlexible, setHotelFlexible] = useState(false);
  const [checkinStart, setCheckinStart] = useState(today);
  const [checkinEnd, setCheckinEnd] = useState(today);
  const [nights, setNights] = useState(1);
  const [rooms, setRooms] = useState(1);
  const [adults, setAdults] = useState(2);
  const [children, setChildren] = useState(0);
  const [hotelSubmitting, setHotelSubmitting] = useState(false);

  const activeAlerts = useMemo(
    () => alerts.filter((alert) => alert.status === "active"),
    [alerts]
  );
  const activeHotelAlerts = useMemo(
    () => hotelAlerts.filter((alert) => alert.status === "active"),
    [hotelAlerts]
  );
  const totalActiveCount = activeAlerts.length + activeHotelAlerts.length;

  async function refreshAlerts() {
    const values = await api.alerts();
    setAlerts(values);
    return values;
  }

  async function refreshHotelAlerts() {
    const values = await api.hotelAlerts();
    setHotelAlerts(values);
    return values;
  }

  useEffect(() => {
    Promise.all([
      api.session(),
      api.locations(),
      api.alerts(),
      api.hotelDestinations(),
      api.hotelAlerts()
    ])
      .then(([sessionValue, locationValues, alertValues, destinationValues, hotelAlertValues]) => {
        setMaxActiveAlerts(sessionValue.max_active_alerts);
        setLocations(locationValues);
        setAlerts(alertValues);
        setHotelDestinations(destinationValues);
        setHotelAlerts(hotelAlertValues);
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
    if (totalActiveCount >= maxActiveAlerts) {
      setLimitDialogOpen(true);
      window.Telegram?.WebApp.HapticFeedback?.notificationOccurred("warning");
      return;
    }
    setSubmitting(true);
    const criteria = {
      trip_type: tripType,
      origin,
      destination,
      outbound_dates: {
        start: toAsciiDigits(outboundStart),
        end: toAsciiDigits(flexible ? outboundEnd : outboundStart)
      },
      outbound_times: { start: outboundTimeStart, end: outboundTimeEnd },
      return_dates:
        tripType === "round_trip"
          ? {
              start: toAsciiDigits(returnStart),
              end: toAsciiDigits(flexible ? returnEnd : returnStart)
            }
          : null,
      return_times:
        tripType === "round_trip"
          ? { start: returnTimeStart, end: returnTimeEnd }
          : null,
      timezone: "Asia/Tehran"
    };
    try {
      await api.createAlert(criteria);
      await refreshAlerts();
      setSuccess("پایش ساخته شد.");
      window.Telegram?.WebApp.HapticFeedback?.notificationOccurred("success");
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 429) {
        await refreshAlerts().catch(() => undefined);
        setLimitDialogOpen(true);
        window.Telegram?.WebApp.HapticFeedback?.notificationOccurred("warning");
        return;
      }
      setError(reason instanceof Error ? reason.message : "ثبت پایش ناموفق بود.");
      window.Telegram?.WebApp.HapticFeedback?.notificationOccurred("error");
    } finally {
      setSubmitting(false);
    }
  }

  async function archiveAlert(id: string) {
    setError("");
    setArchivingId(id);
    try {
      await api.cancelAlert(id);
      const values = await refreshAlerts();
      const activeCount = values.filter((alert) => alert.status === "active").length;
      if (activeCount + activeHotelAlerts.length < maxActiveAlerts) {
        setLimitDialogOpen(false);
      }
      window.Telegram?.WebApp.HapticFeedback?.notificationOccurred("success");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "حذف پایش ناموفق بود.");
    } finally {
      setArchivingId(null);
    }
  }

  function updateCheckinStart(value: string) {
    setCheckinStart(value);
    if (!hotelFlexible || checkinEnd < value) setCheckinEnd(value);
  }

  function toggleHotelFlexible(value: boolean) {
    setHotelFlexible(value);
    if (!value) setCheckinEnd(checkinStart);
  }

  async function submitHotel(event: FormEvent) {
    event.preventDefault();
    setError("");
    setSuccess("");
    if (totalActiveCount >= maxActiveAlerts) {
      setLimitDialogOpen(true);
      window.Telegram?.WebApp.HapticFeedback?.notificationOccurred("warning");
      return;
    }
    setHotelSubmitting(true);
    const criteria = {
      destination: hotelDestination,
      checkin_dates: {
        start: toAsciiDigits(checkinStart),
        end: toAsciiDigits(hotelFlexible ? checkinEnd : checkinStart)
      },
      nights,
      rooms,
      occupancy: { adults, children },
      timezone: "Asia/Tehran"
    };
    try {
      await api.createHotelAlert(criteria);
      await refreshHotelAlerts();
      setSuccess("پایش هتل ساخته شد.");
      window.Telegram?.WebApp.HapticFeedback?.notificationOccurred("success");
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 429) {
        await refreshHotelAlerts().catch(() => undefined);
        setLimitDialogOpen(true);
        window.Telegram?.WebApp.HapticFeedback?.notificationOccurred("warning");
        return;
      }
      setError(reason instanceof Error ? reason.message : "ثبت پایش هتل ناموفق بود.");
      window.Telegram?.WebApp.HapticFeedback?.notificationOccurred("error");
    } finally {
      setHotelSubmitting(false);
    }
  }

  async function archiveHotelAlert(id: string) {
    setError("");
    setArchivingId(id);
    try {
      await api.cancelHotelAlert(id);
      const values = await refreshHotelAlerts();
      const activeCount = values.filter((alert) => alert.status === "active").length;
      if (activeCount + activeAlerts.length < maxActiveAlerts) {
        setLimitDialogOpen(false);
      }
      window.Telegram?.WebApp.HapticFeedback?.notificationOccurred("success");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "حذف پایش ناموفق بود.");
    } finally {
      setArchivingId(null);
    }
  }

  if (loading) {
    return (
      <main className="shell loading">
        <PlaneLoader />
      </main>
    );
  }

  return (
    <main className="shell">
      <header className="hero">
        <div className="plane-mark"><PlaneIcon /></div>
        <h1>پایش سفر</h1>
      </header>

      <div className="segmented" aria-label="نوع پایش">
        <button type="button" className={activeTab === "flight" ? "selected" : ""} onClick={() => setActiveTab("flight")}>پرواز</button>
        <button type="button" className={activeTab === "hotel" ? "selected" : ""} onClick={() => setActiveTab("hotel")}>هتل</button>
      </div>

      {error && <div className="notice error" role="alert">{error}</div>}
      {success && <div className="notice success" role="status">{success}</div>}

      {activeTab === "flight" && (
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

        <button className="primary" type="submit" disabled={submitting || !origin || !destination}>
          {submitting ? <PlaneLoader compact /> : "شروع پایش پرواز"}
        </button>
      </form>
      )}

      {activeTab === "hotel" && (
      <form className="card form-card" onSubmit={submitHotel}>
        <HotelDestinationField
          label="مقصد"
          value={hotelDestination}
          onChange={setHotelDestination}
          destinations={hotelDestinations}
        />

        <div className="section-heading">
          <h2>تاریخ ورود</h2>
          <button type="button" className="calendar-toggle" onClick={() => setCalendarMode(calendarMode === "jalali" ? "gregorian" : "jalali")}>
            {calendarMode === "jalali" ? "نمایش میلادی" : "نمایش شمسی"}
          </button>
        </div>
        <label className="toggle-row">
          <input type="checkbox" checked={hotelFlexible} onChange={(event) => toggleHotelFlexible(event.target.checked)} />
          <span>تاریخ ورود منعطف است</span>
        </label>
        <section className="grid two">
          <DateField label={hotelFlexible ? "از تاریخ" : "تاریخ ورود"} value={checkinStart} onChange={updateCheckinStart} mode={calendarMode} />
          {hotelFlexible && <DateField label="تا تاریخ" value={checkinEnd} onChange={setCheckinEnd} mode={calendarMode} />}
          <StepperField label="تعداد شب" value={nights} onChange={setNights} min={1} max={30} />
          <StepperField label="تعداد اتاق" value={rooms} onChange={setRooms} min={1} max={4} />
        </section>

        <div className="section-heading"><h2>مسافران</h2></div>
        <section className="grid two">
          <StepperField label="بزرگسال" value={adults} onChange={setAdults} min={1} max={6} />
          <StepperField label="کودک" value={children} onChange={setChildren} min={0} max={4} />
        </section>

        <button className="primary" type="submit" disabled={hotelSubmitting || !hotelDestination}>
          {hotelSubmitting ? <PlaneLoader compact /> : "شروع پایش هتل"}
        </button>
      </form>
      )}

      {activeTab === "flight" && activeAlerts.length > 0 && (
        <section className="card alerts-card">
          <div className="section-heading">
            <h2>پایش‌های من</h2>
            <span className="counter">{totalActiveCount} از {maxActiveAlerts}</span>
          </div>
          {activeAlerts.map((alert) => (
            <div className="alert-entry" key={alert.id}>
              <article className="alert-row">
                <div>
                  <strong>{alert.criteria.origin} ← {alert.criteria.destination}</strong>
                  <small>{alert.criteria.outbound_dates.start} تا {alert.criteria.outbound_dates.end}</small>
                </div>
                <button
                  className="delete-alert"
                  type="button"
                  disabled={archivingId === alert.id}
                  onClick={() => archiveAlert(alert.id)}
                >
                  {archivingId === alert.id ? <PlaneLoader compact /> : "حذف"}
                </button>
              </article>
            </div>
          ))}
        </section>
      )}

      {activeTab === "hotel" && activeHotelAlerts.length > 0 && (
        <section className="card alerts-card">
          <div className="section-heading">
            <h2>پایش‌های من</h2>
            <span className="counter">{totalActiveCount} از {maxActiveAlerts}</span>
          </div>
          {activeHotelAlerts.map((alert) => (
            <div className="alert-entry" key={alert.id}>
              <article className="alert-row">
                <div>
                  <strong>{alert.criteria.destination}</strong>
                  <small>{alert.criteria.checkin_dates.start} تا {alert.criteria.checkin_dates.end} · {alert.criteria.nights} شب</small>
                </div>
                <button
                  className="delete-alert"
                  type="button"
                  disabled={archivingId === alert.id}
                  onClick={() => archiveHotelAlert(alert.id)}
                >
                  {archivingId === alert.id ? <PlaneLoader compact /> : "حذف"}
                </button>
              </article>
            </div>
          ))}
        </section>
      )}

      {limitDialogOpen && (
        <div className="modal-backdrop">
          <section
            className="limit-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="limit-dialog-title"
          >
            <button
              className="modal-close"
              type="button"
              aria-label="بستن"
              onClick={() => setLimitDialogOpen(false)}
            >
              ×
            </button>
            <div className="dialog-plane"><PlaneIcon /></div>
            <h2 id="limit-dialog-title">حداکثر {maxActiveAlerts} پایش فعال</h2>
            <p>برای ساخت پایش جدید، ابتدا یکی از پایش‌های فعال را حذف کنید.</p>
            <div className="dialog-alerts">
              {activeAlerts.map((alert) => (
                <div className="dialog-alert" key={alert.id}>
                  <span>
                    <strong>{alert.criteria.origin} ← {alert.criteria.destination}</strong>
                    <small>{alert.criteria.outbound_dates.start}</small>
                  </span>
                  <button
                    type="button"
                    disabled={archivingId === alert.id}
                    onClick={() => archiveAlert(alert.id)}
                  >
                    {archivingId === alert.id ? <PlaneLoader compact /> : "حذف"}
                  </button>
                </div>
              ))}
              {activeHotelAlerts.map((alert) => (
                <div className="dialog-alert" key={alert.id}>
                  <span>
                    <strong>🏨 {alert.criteria.destination}</strong>
                    <small>{alert.criteria.checkin_dates.start}</small>
                  </span>
                  <button
                    type="button"
                    disabled={archivingId === alert.id}
                    onClick={() => archiveHotelAlert(alert.id)}
                  >
                    {archivingId === alert.id ? <PlaneLoader compact /> : "حذف"}
                  </button>
                </div>
              ))}
            </div>
          </section>
        </div>
      )}
    </main>
  );
}
