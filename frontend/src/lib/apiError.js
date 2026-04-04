export function getApiErrorMessage(err) {
  const d = err?.response?.data?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) {
    return d.map((x) => x.msg || JSON.stringify(x)).join("; ");
  }
  if (d && typeof d === "object") return JSON.stringify(d);
  return err?.message || "Request failed";
}
