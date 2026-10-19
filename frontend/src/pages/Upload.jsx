import { useState, useRef, useEffect } from 'react';
import { FiUploadCloud, FiFile, FiCheckCircle, FiAlertCircle } from 'react-icons/fi';
import { uploadAPI } from '../api/client';
import { formatMonthYear, getErrorMessage } from '../utils/download';

export default function Upload() {
  const [excelFile, setExcelFile] = useState(null);
  const [pdfFile, setPdfFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [status, setStatus] = useState(null); // { type: 'success'|'error', message: '' }
  const [currentBatchId, setCurrentBatchId] = useState(null);
  // { batch, report } while an upload waits for the user to confirm or cancel it
  const [review, setReview] = useState(null);
  const [reviewBusy, setReviewBusy] = useState(false);
  const [history, setHistory] = useState([]);
  // What the server is doing right now: { stage: 'checking'|'importing', monthYear, processed, total, startedAt }
  const [job, setJob] = useState(null);

  const excelInputRef = useRef(null);
  const pdfInputRef = useRef(null);

  useEffect(() => {
    // Check if there is an active upload to resume tracking
    uploadAPI.list().then(res => {
      if (res.data && res.data.uploads && res.data.uploads.length > 0) {
        const latest = res.data.uploads[0];
        if (['analyzing', 'awaiting_review', 'processing'].includes(latest.status)) {
          setCurrentBatchId(latest.id);
          setUploading(true);
        }
      }
    }).catch(console.error);
  }, []);

  // Refresh the history whenever an upload starts, waits for review or finishes
  useEffect(() => {
    uploadAPI.list()
      .then(res => setHistory(res.data.uploads || []))
      .catch(err => console.error("Failed to load upload history", err));
  }, [currentBatchId, review]);

  const handleReprocess = async (upload) => {
    const ok = window.confirm(
      `Re-read the stored payslip PDF for ${formatMonthYear(upload.month_year)} with the latest reading rules?\n\n`
      + 'You will see the check results first; nothing changes until you confirm the import.'
    );
    if (!ok) return;
    setUploading(true);
    setStatus(null);
    try {
      const res = await uploadAPI.reprocess(upload.id);
      setJob({ stage: 'checking', monthYear: res.data.batch.month_year, startedAt: res.data.batch.uploaded_at });
      setCurrentBatchId(res.data.batch.id);
    } catch (err) {
      setStatus({ type: 'error', message: await getErrorMessage(err, 'The upload could not be re-processed.') });
      setUploading(false);
    }
  };

  // Poll for status while a batch is being checked or imported
  useEffect(() => {
    if (!currentBatchId) return;

    const poll = async () => {
      try {
        const res = await uploadAPI.status(currentBatchId);
        const batch = res.data.batch;
        const working = { monthYear: batch.month_year, startedAt: batch.uploaded_at };

        if (batch.status === 'analyzing' || batch.status === 'processing') {
          setStatus(null);
          setJob({
            ...working,
            stage: batch.status === 'analyzing' ? 'checking' : 'importing',
            processed: batch.records_processed || 0,
            total: batch.total_records || 0,
          });
          return; // keep polling
        }
        setJob(null);

        if (batch.status === 'awaiting_review') {
          setReview({ batch, report: res.data.report });
          setStatus(null);
          setCurrentBatchId(null);
        } else if (batch.status === 'cancelled') {
          setStatus({ type: 'info', message: 'This upload was discarded. Nothing was imported.' });
          setCurrentBatchId(null);
          setUploading(false);
        } else if (batch.status === 'completed') {
          setStatus({
            type: 'success',
            message: `Successfully processed ${batch.total_records} records for ${formatMonthYear(batch.month_year)}!`
              + (batch.error_message ? ` Note: ${batch.error_message}` : '')
          });
          setCurrentBatchId(null);
          setUploading(false);
        } else if (batch.status === 'failed') {
          setStatus({ type: 'error', message: `Processing failed: ${batch.error_message}` });
          setCurrentBatchId(null);
          setUploading(false);
        }
      } catch (err) {
        console.error("Failed to check status", err);
      }
    };

    poll();
    const interval = setInterval(poll, 3000);
    return () => clearInterval(interval);
  }, [currentBatchId]);

  const handleConfirm = async () => {
    setReviewBusy(true);
    try {
      const res = await uploadAPI.confirm(review.batch.id);
      const batch = res.data.batch;
      setReview(null);
      setStatus(null);
      setJob({ stage: 'importing', monthYear: batch.month_year, startedAt: batch.uploaded_at, processed: 0, total: batch.total_records || 0 });
      setCurrentBatchId(batch.id);
    } catch (err) {
      setStatus({ type: 'error', message: await getErrorMessage(err, 'The import could not be started.') });
      setReview(null);
      setUploading(false);
    } finally {
      setReviewBusy(false);
    }
  };

  const handleCancelReview = async () => {
    setReviewBusy(true);
    try {
      await uploadAPI.cancel(review.batch.id);
      setStatus({ type: 'info', message: 'Upload discarded. Nothing was imported.' });
    } catch (err) {
      setStatus({ type: 'error', message: await getErrorMessage(err, 'The upload could not be discarded.') });
    } finally {
      setReview(null);
      setUploading(false);
      setReviewBusy(false);
    }
  };

  const handleFileChange = (e, type) => {
    const file = e.target.files[0];
    if (!file) return;
    
    if (type === 'excel') setExcelFile(file);
    if (type === 'pdf') setPdfFile(file);
  };

  const handleUpload = async () => {
    if (!excelFile && !pdfFile) {
      setStatus({ type: 'error', message: 'Please select at least one file to upload.' });
      return;
    }

    setUploading(true);
    setStatus(null);
    setProgress(0);

    const formData = new FormData();
    if (excelFile) formData.append('excel_file', excelFile);
    if (pdfFile) formData.append('pdf_file', pdfFile);

    try {
      const res = await uploadAPI.upload(formData, (progressEvent) => {
        const percentCompleted = Math.round((progressEvent.loaded * 100) / progressEvent.total);
        setProgress(percentCompleted);
      });
      
      // Upload finished, now backend is processing
      setJob({ stage: 'checking', monthYear: res.data.batch.month_year, startedAt: res.data.batch.uploaded_at });
      setCurrentBatchId(res.data.batch.id);
      
      // Clear files
      setExcelFile(null);
      setPdfFile(null);
      if (excelInputRef.current) excelInputRef.current.value = '';
      if (pdfInputRef.current) pdfInputRef.current.value = '';
      
    } catch (err) {
      console.error("Upload failed:", err);
      const fallback = `Upload failed (the server answered with error ${err.response?.status}). Please try again.`;
      setStatus({ type: 'error', message: await getErrorMessage(err, fallback) });
      setUploading(false);
    }
  };

  return (
    <>
    <div className="card" style={{ maxWidth: '800px', margin: '0 auto' }}>
      <div className="card-header">
        <h2><FiUploadCloud style={{ marginRight: '8px' }} /> Upload Monthly Payroll Data</h2>
      </div>

      {status && (
        <div style={{ 
          padding: '16px', 
          marginBottom: '24px', 
          borderRadius: 'var(--radius-md)',
          display: 'flex',
          alignItems: 'center',
          gap: '12px',
          background: status.type === 'success' ? 'var(--accent-emerald-dim)' : 
                     status.type === 'error' ? 'var(--accent-rose-dim)' : 
                     'var(--accent-blue-dim)',
          color: status.type === 'success' ? 'var(--accent-emerald)' : 
                 status.type === 'error' ? 'var(--accent-rose)' : 
                 'var(--accent-blue)',
          border: `1px solid ${
                 status.type === 'success' ? 'rgba(16, 185, 129, 0.2)' : 
                 status.type === 'error' ? 'rgba(244, 63, 94, 0.2)' : 
                 'rgba(59, 130, 246, 0.2)'}`
        }}>
          {status.type === 'success' ? <FiCheckCircle size={20} /> : <FiAlertCircle size={20} />}
          <span>{status.message}</span>
        </div>
      )}

      {uploading && !currentBatchId && !review && !job && (
        <JobProgress job={{ stage: 'uploading', processed: progress, total: 100 }} />
      )}
      {job && <JobProgress job={job} />}

      {review && (
        <ReviewPanel
          review={review}
          busy={reviewBusy}
          onConfirm={handleConfirm}
          onCancel={handleCancelReview}
        />
      )}

      <p style={{ marginBottom: '24px', fontSize: '0.85rem', color: 'var(--text-muted)' }}>
        The payroll month and year are read automatically from the payslip PDF.
        Files are checked first; nothing is imported until you confirm.
      </p>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px', marginBottom: '24px' }}>
        {/* Excel Upload */}
        <div>
          <label className="form-label">Nominal Payroll (Excel)</label>
          <div 
            className={`upload-dropzone ${excelFile ? 'active' : ''}`}
            onClick={() => !uploading && excelInputRef.current?.click()}
          >
            <FiFile className="upload-dropzone-icon" />
            <h3>{excelFile ? 'File Selected' : 'Select Excel File'}</h3>
            <p>.xlsx or .xls files only</p>
            <input 
              type="file" 
              accept=".xlsx,.xls" 
              style={{ display: 'none' }} 
              ref={excelInputRef}
              onChange={(e) => handleFileChange(e, 'excel')}
              disabled={uploading}
            />
          </div>
          {excelFile && (
            <div className="upload-file-item" style={{ marginTop: '12px' }}>
              <FiFile className="file-icon" />
              <span className="file-name">{excelFile.name}</span>
            </div>
          )}
        </div>

        {/* PDF Upload */}
        <div>
          <label className="form-label">Bulk Payslips (PDF)</label>
          <div 
            className={`upload-dropzone ${pdfFile ? 'active' : ''}`}
            onClick={() => !uploading && pdfInputRef.current?.click()}
          >
            <FiFile className="upload-dropzone-icon" />
            <h3>{pdfFile ? 'File Selected' : 'Select PDF File'}</h3>
            <p>.pdf files only (can be large)</p>
            <input 
              type="file" 
              accept=".pdf" 
              style={{ display: 'none' }} 
              ref={pdfInputRef}
              onChange={(e) => handleFileChange(e, 'pdf')}
              disabled={uploading}
            />
          </div>
          {pdfFile && (
            <div className="upload-file-item" style={{ marginTop: '12px' }}>
              <FiFile className="file-icon" />
              <span className="file-name">{pdfFile.name}</span>
            </div>
          )}
        </div>
      </div>

      <div style={{ marginTop: '32px', textAlign: 'right' }}>
        <button 
          className="btn btn-primary btn-lg" 
          onClick={handleUpload}
          disabled={uploading || (!excelFile && !pdfFile)}
          style={{ width: '100%' }}
        >
          {review ? 'Waiting for your review above' : uploading ? (currentBatchId ? 'Working...' : 'Uploading Files...') : 'Upload and Check'}
        </button>
      </div>
    </div>

    <UploadHistory uploads={history} busy={uploading} onReprocess={handleReprocess} />
    </>
  );
}

const STATUS_BADGES = {
  completed: 'badge-emerald',
  failed: 'badge-rose',
  cancelled: 'badge-blue',
};

function UploadHistory({ uploads, busy, onReprocess }) {
  const [showAll, setShowAll] = useState(false);
  if (!uploads.length) return null;
  const shown = showAll ? uploads : uploads.slice(0, 10);

  return (
    <div className="card" style={{ maxWidth: '800px', margin: '24px auto 0' }}>
      <div className="card-header">
        <h2>Upload History</h2>
      </div>
      <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)', marginBottom: '12px' }}>
        Re-process reads a stored payslip PDF again with the latest reading rules (for example to fill in
        earnings and deductions on older months). You review the result before anything changes.
      </p>
      <table>
        <thead>
          <tr>
            <th>Month</th>
            <th>Files</th>
            <th>Status</th>
            <th>Records</th>
            <th>Uploaded</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {shown.map(u => (
            <tr key={u.id} style={{ cursor: 'default' }}>
              <td style={{ whiteSpace: 'nowrap' }}>{formatMonthYear(u.month_year)}</td>
              <td style={{ fontSize: '0.75rem', maxWidth: '220px', overflowWrap: 'anywhere' }}>
                {[u.pdf_filename, u.excel_filename].filter(Boolean).join(', ')}
              </td>
              <td>
                <span className={`badge ${STATUS_BADGES[u.status] || 'badge-amber'}`} title={u.error_message || ''}>
                  {u.status.replace('_', ' ')}
                </span>
              </td>
              <td>{u.status === 'completed' ? u.total_records?.toLocaleString() : '—'}</td>
              <td style={{ fontSize: '0.75rem', whiteSpace: 'nowrap' }}>
                {u.uploaded_at ? new Date(u.uploaded_at).toLocaleDateString() : ''}
              </td>
              <td style={{ textAlign: 'right' }}>
                {u.status === 'completed' && u.pdf_filename && (
                  <button className="btn btn-sm btn-secondary" disabled={busy} onClick={() => onReprocess(u)}>
                    Re-process
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {uploads.length > 10 && (
        <div style={{ textAlign: 'center', marginTop: '12px' }}>
          <button className="btn btn-sm btn-ghost" onClick={() => setShowAll(prev => !prev)}>
            {showAll ? 'Show fewer' : `Show all ${uploads.length} uploads`}
          </button>
        </div>
      )}
    </div>
  );
}

const LEVEL_STYLES = {
  error: { color: 'var(--accent-rose)', background: 'var(--accent-rose-dim)', label: 'Error' },
  warning: { color: 'var(--accent-amber)', background: 'var(--accent-amber-dim)', label: 'Check' },
  info: { color: 'var(--accent-blue)', background: 'var(--accent-blue-dim)', label: 'Info' },
  ok: { color: 'var(--accent-emerald)', background: 'var(--accent-emerald-dim)', label: 'OK' },
};

const cellStyle = { padding: '6px 10px', fontSize: '0.8rem', textAlign: 'left' };

function ReviewPanel({ review, busy, onConfirm, onCancel }) {
  const { batch, report } = review;
  if (!report) return null;
  const pdf = report.pdf;
  const excel = report.excel;

  return (
    <div style={{ border: '1px solid var(--border-secondary)', borderRadius: 'var(--radius-md)', padding: '20px', marginBottom: '24px' }}>
      <h3 style={{ marginBottom: '4px' }}>Review before import — {report.month_label || formatMonthYear(batch.month_year)}</h3>
      <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)', marginBottom: '16px' }}>
        {[batch.pdf_filename, batch.excel_filename].filter(Boolean).join(' + ')}
        {' · '}
        {report.errors > 0
          ? `${report.errors} error(s) must be fixed before this upload can be imported.`
          : report.warnings > 0
            ? `${report.warnings} item(s) to check. Nothing has been imported yet.`
            : 'All checks passed. Nothing has been imported yet.'}
      </p>

      <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', marginBottom: '16px' }}>
        {pdf && <SummaryTile label="Payslips read" value={pdf.payslips?.toLocaleString()} detail={`from ${pdf.pages?.toLocaleString()} pages`} />}
        {pdf?.previous_month && (
          <SummaryTile
            label={`vs ${formatMonthYear(pdf.previous_month)}`}
            value={`${pdf.payslips - pdf.previous_count >= 0 ? '+' : ''}${pdf.payslips - pdf.previous_count}`}
            detail={`${pdf.joined} new · ${pdf.left} left`}
          />
        )}
        {pdf && <SummaryTile label="Fully itemised" value={pdf.payslips ? `${Math.round(pdf.fully_itemised * 100 / pdf.payslips)}%` : '—'} detail="breakdown matches totals" />}
        {excel && <SummaryTile label="Nominal roll" value={excel.rows?.toLocaleString()} detail="employees read" />}
      </div>

      <ul style={{ listStyle: 'none', padding: 0, margin: '0 0 16px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
        {report.checks.map((check, i) => {
          const style = LEVEL_STYLES[check.level] || LEVEL_STYLES.info;
          return (
            <li key={i} style={{ display: 'flex', gap: '10px', alignItems: 'flex-start', fontSize: '0.85rem' }}>
              <span className="badge" style={{ color: style.color, background: style.background, minWidth: '52px', textAlign: 'center' }}>
                {style.label}
              </span>
              <span>{check.message}</span>
            </li>
          );
        })}
      </ul>

      {excel?.columns && Object.keys(excel.columns).length > 0 && (
        <details style={{ marginBottom: '12px' }}>
          <summary style={{ cursor: 'pointer', fontSize: '0.85rem' }}>Excel columns recognised</summary>
          <table style={{ marginTop: '8px' }}>
            <thead><tr><th style={cellStyle}>Field</th><th style={cellStyle}>Column in your sheet</th></tr></thead>
            <tbody>
              {Object.entries(excel.columns).map(([field, header]) => (
                <tr key={field} style={{ cursor: 'default' }}><td style={cellStyle}>{field}</td><td style={cellStyle}>{header}</td></tr>
              ))}
            </tbody>
          </table>
        </details>
      )}

      {pdf?.examples?.length > 0 && (
        <details style={{ marginBottom: '12px' }}>
          <summary style={{ cursor: 'pointer', fontSize: '0.85rem' }}>Pages to look at ({pdf.examples.length})</summary>
          <table style={{ marginTop: '8px' }}>
            <thead><tr><th style={cellStyle}>Page</th><th style={cellStyle}>IPPIS</th><th style={cellStyle}>Name</th><th style={cellStyle}>Issue</th></tr></thead>
            <tbody>
              {pdf.examples.map((ex, i) => (
                <tr key={i} style={{ cursor: 'default' }}>
                  <td style={cellStyle}>{ex.page}</td>
                  <td style={cellStyle}>{ex.ippis ?? '—'}</td>
                  <td style={cellStyle}>{ex.name ?? '—'}</td>
                  <td style={cellStyle}>{ex.issue}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}

      <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
        <button className="btn btn-secondary" onClick={onCancel} disabled={busy}>
          Cancel upload
        </button>
        <button className="btn btn-primary" onClick={onConfirm} disabled={busy || !report.can_import}>
          {busy ? 'Please wait...' : report.warnings > 0 ? 'Import anyway' : 'Confirm import'}
        </button>
      </div>
    </div>
  );
}

function SummaryTile({ label, value, detail }) {
  return (
    <div style={{ background: 'var(--bg-secondary)', borderRadius: 'var(--radius-md)', padding: '10px 14px', minWidth: '140px' }}>
      <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', textTransform: 'uppercase' }}>{label}</div>
      <div style={{ fontSize: '1.3rem', fontWeight: 700 }}>{value}</div>
      <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{detail}</div>
    </div>
  );
}

const STAGES = {
  uploading: {
    title: 'Sending the files to the server',
    hint: 'Keep this page open until the files have finished sending.',
  },
  checking: {
    title: 'Checking the files',
    hint: 'Reading every page and checking the figures. Nothing is imported yet. This usually takes under a minute.',
  },
  importing: {
    title: 'Importing',
    hint: 'You can leave this page; the import carries on on the server and this page picks it up again when you return.',
  },
};

// Server times are UTC without a zone marker; read them as UTC
function parseServerTime(value) {
  if (!value) return null;
  const ms = Date.parse(/[zZ]|[+-]\d\d:?\d\d$/.test(value) ? value : `${value}Z`);
  return Number.isNaN(ms) ? null : ms;
}

function formatElapsed(ms) {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(seconds / 60);
  return minutes ? `${minutes} min ${String(seconds % 60).padStart(2, '0')} s` : `${seconds} s`;
}

function JobProgress({ job }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  const stage = STAGES[job.stage];
  const started = parseServerTime(job.startedAt);
  const known = job.total > 0 && (job.stage !== 'importing' || job.processed > 0);
  const percent = known ? Math.min(100, Math.round((job.processed * 100) / job.total)) : null;

  let detail;
  if (job.stage === 'uploading') {
    detail = `${job.processed}% sent`;
  } else if (job.stage === 'importing' && !known) {
    detail = 'Saving the PDF to storage and preparing the import...';
  } else if (job.stage === 'importing') {
    detail = `${job.processed.toLocaleString()} of ${job.total.toLocaleString()} records saved (${percent}%)`;
  } else {
    detail = 'Reading pages...';
  }

  return (
    <div style={{
      padding: '16px', marginBottom: '24px', borderRadius: 'var(--radius-md)',
      background: 'var(--accent-blue-dim)', border: '1px solid rgba(59, 130, 246, 0.2)',
    }} role="status" aria-live="polite">
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', flexWrap: 'wrap', marginBottom: '8px' }}>
        <strong style={{ color: 'var(--accent-blue)' }}>
          {stage.title}{job.monthYear ? ` — ${formatMonthYear(job.monthYear)}` : ''}
        </strong>
        {started && <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Elapsed {formatElapsed(now - started)}</span>}
      </div>
      <div className="progress-bar-container">
        {percent === null
          ? <div className="progress-bar indeterminate"></div>
          : <div className="progress-bar" style={{ width: `${percent}%` }}></div>}
      </div>
      <div style={{ fontSize: '0.85rem', marginTop: '8px' }}>{detail}</div>
      <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '4px' }}>{stage.hint}</div>
    </div>
  );
}
