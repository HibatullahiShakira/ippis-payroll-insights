/**
 * Helpers for file downloads/previews and for reading API error messages.
 */

/**
 * Extract the server's error message from a failed request.
 * Download requests use responseType 'blob', so the JSON error body arrives as a Blob.
 */
export async function getErrorMessage(err, fallback) {
  if (!err?.response) {
    return 'Could not reach the server. It may be waking up, the connection dropped, or the request took too long — please try again.';
  }
  if (err.response.status === 502 || err.response.status === 503 || err.response.status === 504) {
    return `The server stopped responding while handling this request (error ${err.response.status}). It may have restarted or run out of memory — please try again in a minute.`;
  }
  const data = err.response.data;
  try {
    const body = data instanceof Blob ? JSON.parse(await data.text()) : data;
    if (body?.error) return body.error;
  } catch {
    // Not a JSON body — fall through to the generic message
  }
  return fallback;
}

/** Trigger a browser download of a Blob. */
export function saveBlob(blob, filename) {
  const url = window.URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.setAttribute('download', filename);
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => window.URL.revokeObjectURL(url), 60000);
}

/**
 * Open a new tab for a PDF that is still being generated.
 *
 * Must be called directly from the click handler: browsers block window.open()
 * once the click is no longer "fresh", which is the case after a slow request.
 */
export function openPdfTab() {
  const tab = window.open('', '_blank');
  if (tab) {
    tab.document.title = 'Preparing PDF…';
    tab.document.body.style.cssText = 'font-family: sans-serif; padding: 24px; background: #0f172a; color: #e2e8f0;';
    tab.document.body.textContent = 'Preparing PDF, please wait…';
  }
  return {
    show(blob) {
      const url = window.URL.createObjectURL(blob);
      if (tab && !tab.closed) {
        tab.location.href = url;
      } else if (!window.open(url, '_blank')) {
        // Pop-ups are blocked entirely — fall back to downloading the file
        saveBlob(blob, 'payslips.pdf');
      }
    },
    close() {
      if (tab && !tab.closed) tab.close();
    },
  };
}

/** Turn any text into a safe filename fragment. */
export function safeFilename(text, fallback = 'file') {
  return (text || '').replace(/[^A-Za-z0-9]+/g, '_').replace(/^_+|_+$/g, '') || fallback;
}

/** '2026-08' -> 'August 2026' */
export function formatMonthYear(myStr) {
  if (!myStr) return '';
  const parts = myStr.split('-');
  if (parts.length === 2) {
    const monthNames = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
    const monthIndex = parseInt(parts[1], 10) - 1;
    if (monthIndex >= 0 && monthIndex < 12) {
      return `${monthNames[monthIndex]} ${parts[0]}`;
    }
  }
  return myStr;
}
