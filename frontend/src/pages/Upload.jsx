import { useState, useRef, useEffect } from 'react';
import { FiUploadCloud, FiFile, FiCheckCircle, FiAlertCircle } from 'react-icons/fi';
import { uploadAPI } from '../api/client';

export default function Upload() {
  const [monthYear, setMonthYear] = useState('');
  const [excelFile, setExcelFile] = useState(null);
  const [pdfFile, setPdfFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [status, setStatus] = useState(null); // { type: 'success'|'error', message: '' }
  const [currentBatchId, setCurrentBatchId] = useState(null);
  
  const excelInputRef = useRef(null);
  const pdfInputRef = useRef(null);

  // Auto-set current month (e.g., "2026-04")
  useEffect(() => {
    const now = new Date();
    const current = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
    setMonthYear(current);
  }, []);

  // Poll for status if a batch is processing
  useEffect(() => {
    if (!currentBatchId) return;

    const interval = setInterval(async () => {
      try {
        const res = await uploadAPI.status(currentBatchId);
        const batch = res.data.batch;
        
        if (batch.status === 'completed') {
          setStatus({ type: 'success', message: `Successfully processed ${batch.total_records} records!` });
          setCurrentBatchId(null);
          setUploading(false);
        } else if (batch.status === 'failed') {
          setStatus({ type: 'error', message: `Processing failed: ${batch.error_message}` });
          setCurrentBatchId(null);
          setUploading(false);
        } else if (batch.status === 'processing') {
          if (batch.total_records > 0) {
             setStatus({ type: 'info', message: `Processing in background: ${batch.records_processed} of ${batch.total_records} pages parsed...` });
          } else {
             setStatus({ type: 'info', message: 'Analyzing document structure... (This may take a moment for large files)' });
          }
        }
        // If processing, keep polling
      } catch (err) {
        console.error("Failed to check status", err);
      }
    }, 3000);

    return () => clearInterval(interval);
  }, [currentBatchId]);

  const handleFileChange = (e, type) => {
    const file = e.target.files[0];
    if (!file) return;
    
    if (type === 'excel') setExcelFile(file);
    if (type === 'pdf') setPdfFile(file);
  };

  const handleUpload = async () => {
    if (!monthYear) {
      setStatus({ type: 'error', message: 'Please select a month and year.' });
      return;
    }
    if (!excelFile && !pdfFile) {
      setStatus({ type: 'error', message: 'Please select at least one file to upload.' });
      return;
    }

    setUploading(true);
    setStatus(null);
    setProgress(0);

    const formData = new FormData();
    formData.append('month_year', monthYear);
    if (excelFile) formData.append('excel_file', excelFile);
    if (pdfFile) formData.append('pdf_file', pdfFile);

    try {
      const res = await uploadAPI.upload(formData, (progressEvent) => {
        const percentCompleted = Math.round((progressEvent.loaded * 100) / progressEvent.total);
        setProgress(percentCompleted);
      });
      
      // Upload finished, now backend is processing
      setStatus({ type: 'info', message: 'Upload complete. Processing files in background...' });
      setCurrentBatchId(res.data.batch.id);
      
      // Clear files
      setExcelFile(null);
      setPdfFile(null);
      if (excelInputRef.current) excelInputRef.current.value = '';
      if (pdfInputRef.current) pdfInputRef.current.value = '';
      
    } catch (err) {
      setStatus({ type: 'error', message: err.response?.data?.error || 'Upload failed' });
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

      <div className="form-group" style={{ marginBottom: '24px' }}>
        <label className="form-label">Month & Year</label>
        <input 
          type="month" 
          className="form-input" 
          value={monthYear}
          onChange={(e) => setMonthYear(e.target.value)}
          disabled={uploading}
        />
      </div>

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
