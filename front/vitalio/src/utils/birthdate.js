function expandTwoDigitYear(yy) {
  const currentYear = new Date().getFullYear()
  const century = Math.floor(currentYear / 100) * 100
  const candidate = century + yy
  if (candidate > currentYear + 1) return candidate - 100
  return candidate
}

/** Parse JJ/MM/AA, JJ/MM/AAAA, or AAAA-MM-JJ → { year, month, day } or null */
export function parseBirthdate(value) {
  const s = String(value || '').trim()
  if (!s) return null

  let m = s.match(/^(\d{4})-(\d{2})-(\d{2})/)
  if (m) {
    return { year: +m[1], month: +m[2], day: +m[3] }
  }

  m = s.match(/^(\d{1,2})\/(\d{1,2})\/(\d{2,4})$/)
  if (m) {
    const day = +m[1]
    const month = +m[2]
    let year = +m[3]
    if (year < 100) year = expandTwoDigitYear(year)
    return { year, month, day }
  }

  return null
}

function isValidDateParts({ year, month, day }) {
  if (month < 1 || month > 12 || day < 1 || day > 31) return false
  const d = new Date(year, month - 1, day)
  return d.getFullYear() === year && d.getMonth() === month - 1 && d.getDate() === day
}

/** Normalize any supported birthdate input to AAAA-MM-JJ (API storage). */
export function birthdateToISO(value) {
  const p = parseBirthdate(value)
  if (!p || !isValidDateParts(p)) return null
  const mm = String(p.month).padStart(2, '0')
  const dd = String(p.day).padStart(2, '0')
  return `${p.year}-${mm}-${dd}`
}

/** Display birthdate as JJ/MM/AA. */
export function formatBirthdateFR(value) {
  const p = parseBirthdate(value)
  if (!p || !isValidDateParts(p)) return String(value || '').trim()
  const yy = String(p.year % 100).padStart(2, '0')
  return `${String(p.day).padStart(2, '0')}/${String(p.month).padStart(2, '0')}/${yy}`
}

export function computeAgeFromBirthdate(bd) {
  const iso = birthdateToISO(bd)
  if (!iso) return null
  const [y, m, d] = iso.split('-').map((x) => parseInt(x, 10))
  const birth = new Date(y, m - 1, d)
  if (Number.isNaN(birth.getTime())) return null
  const today = new Date()
  let age = today.getFullYear() - birth.getFullYear()
  const md = today.getMonth() - birth.getMonth()
  if (md < 0 || (md === 0 && today.getDate() < birth.getDate())) age -= 1
  return age >= 0 && age <= 150 ? age : null
}
