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

  // Poll for status while a batch is being checked or imported
  useEffect(() => {
    if (!currentBatchId) return;

    const poll = async () => {
      try {
        const res = await uploadAPI.status(currentBatchId);
        const batch = res.data.batch;

        if (batch.status === 'awaiting_review') {
          setReview({ batch, report: res.data.report });
          setStatus(null);
          setCurrentBatchId(null);
        } else if (batch.status === 'analyzing') {
          setStatus({ type: 'info', message: `Checking the files for ${formatMonthYear(batch.month_year)} before anything is imported...` });
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
        } else if (batch.status === 'processing') {
          setStatus({
            type: 'info',
            message: batch.total_records > 0
              ? `Importing: ${batch.records_processed} of ${batch.total_records} payslips saved...`
              : 'Importing the files...'
          });
        }
        // Otherwise keep polling
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
      setReview(null);
      setStatus({ type: 'info', message: 'Import started...' });
      setCurrentBatchId(res.data.batch.id);
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
      setStatus({ type: 'info', message: `Upload complete — detected ${formatMonthYear(res.data.batch.month_year)}. Checking the files before anything is imported...` });
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

      {uploading && (
        <div className="upload-progress">
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem' }}>
            <span>Uploading...</span>
            <span>{progress}%</span>
          </div>
          <div className="progress-bar-container">
            <div className="progress-bar" style={{ width: `${progress}%` }}></div>
          </div>
        </div>
      )}

      <div style={{ marginTop: '32px', textAlign: 'right' }}>
        <button 
          className="btn btn-primary btn-lg" 
          onClick={handleUpload}
          disabled={uploading || (!excelFile && !pdfFile)}
          style={{ width: '100%' }}
        >
          {uploading ? (currentBatchId ? 'Processing Data...' : 'Uploading Files...') : 'Upload and Process'}
        </button>
      </div>
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
