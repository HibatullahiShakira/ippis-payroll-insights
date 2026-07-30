import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { FiArrowLeft, FiUser, FiBriefcase, FiCreditCard, FiFileText } from 'react-icons/fi';
import { employeesAPI, payslipsAPI, exportAPI } from '../api/client';

export default function EmployeeDetail() {
  const { id } = useParams();
  const [employee, setEmployee] = useState(null);
  const [payslipHistory, setPayslipHistory] = useState([]);
  const [jobHistory, setJobHistory] = useState([]);
  const [activeTab, setActiveTab] = useState('payslips');
  const [selectedPayslipId, setSelectedPayslipId] = useState(null);
  const [fullPayslip, setFullPayslip] = useState(null);
  const [loading, setLoading] = useState(true);
  const [payslipLoading, setPayslipLoading] = useState(false);
  const [pdfLoading, setPdfLoading] = useState(false);
  
  const [filterYear, setFilterYear] = useState('');
  const [filterMonth, setFilterMonth] = useState('');
  const [bulkPdfLoading, setBulkPdfLoading] = useState(false);

  useEffect(() => {
    const fetchEmployee = async () => {
      try {
        const res = await employeesAPI.get(id);
        setEmployee(res.data.employee);
        setPayslipHistory(res.data.payslips);
        
        if (res.data.payslips.length > 0) {
          setSelectedPayslipId(res.data.payslips[0].id);
        }

        try {
          const historyRes = await employeesAPI.history(id);
          setJobHistory(historyRes.data.history);
        } catch (hErr) {
          console.error("Failed to load job history, maybe table doesn't exist yet:", hErr);
          setJobHistory([]);
        }
      } catch (err) {
        console.error("Failed to load employee:", err);
      } finally {
        setLoading(false);
      }
    };
    fetchEmployee();
  }, [id]);

  useEffect(() => {
    const fetchFullPayslip = async () => {
      if (!selectedPayslipId) return;
      setPayslipLoading(true);
      try {
        const res = await payslipsAPI.get(selectedPayslipId);
        setFullPayslip(res.data.payslip);
      } catch (err) {
        console.error("Failed to load full payslip:", err);
      } finally {
        setPayslipLoading(false);
      }
    };
    fetchFullPayslip();
  }, [selectedPayslipId]);

  const handleDownloadPdf = async (viewOnly = false) => {
    if (!selectedPayslipId || !fullPayslip) return;
    setPdfLoading(true);
    try {
      const res = await payslipsAPI.getPdfBlob(selectedPayslipId);
      const file = new Blob([res.data], { type: 'application/pdf' });
      const fileURL = URL.createObjectURL(file);
      
      if (viewOnly) {
        window.open(fileURL, '_blank');
      } else {
        const link = document.createElement('a');
        link.href = fileURL;
        const safeName = employee.name.replace(/ /g, '_');
        link.download = `Payslip_${safeName}_${fullPayslip.month_year}.pdf`;
        link.click();
      }
    } catch (err) {
      console.error("Failed to download PDF:", err);
      alert("Failed to get PDF. Note: You may need to re-upload the bulk PDF so the system can save page numbers.");
    } finally {
      setPdfLoading(false);
    }
  };

  const formatCurrency = (amount) => {
    if (amount === null || amount === undefined) return '₦0.00';
    return `₦${amount.toLocaleString('en-NG', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  };

  const formatMonthYear = (myStr) => {
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
  };

  const availableYears = [...new Set(payslipHistory.map(p => {
    if (!p.month_year) return '';
    const parts = p.month_year.split('-');
    return parts[0];
  }))].filter(Boolean).sort((a, b) => b.localeCompare(a)); // sort descending

  const allMonths = [
    { value: '01', label: 'January' },
    { value: '02', label: 'February' },
    { value: '03', label: 'March' },
    { value: '04', label: 'April' },
    { value: '05', label: 'May' },
    { value: '06', label: 'June' },
    { value: '07', label: 'July' },
    { value: '08', label: 'August' },
    { value: '09', label: 'September' },
    { value: '10', label: 'October' },
    { value: '11', label: 'November' },
    { value: '12', label: 'December' }
  ];

  const filteredPayslips = payslipHistory.filter(p => {
    if (!p.month_year) return true;
    const parts = p.month_year.split('-');
    const pYear = parts[0];
    const pMonth = parts.length > 1 ? parts[1] : null;

    if (filterYear && pYear !== filterYear) return false;
    if (filterMonth && pMonth !== filterMonth) return false;
    return true;
  });

  const handleEmployeeBulkPdf = async (viewOnly = false) => {
    if (filteredPayslips.length === 0) {
      alert("No payslips match the current filters.");
      return;
    }
    setBulkPdfLoading(true);
    try {
      const payslipIds = filteredPayslips.map(p => p.id).join(',');
      const res = await exportAPI.employeeBulkPayslipsPDF({ employee_id: id, payslip_ids: payslipIds });
      const url = window.URL.createObjectURL(new Blob([res.data], { type: 'application/pdf' }));
      if (viewOnly) {
        window.open(url, '_blank');
      } else {
        const link = document.createElement('a');
        link.href = url;
        const safeName = employee.name.replace(/ /g, '_');
        link.setAttribute('download', `Payslips_${safeName}.pdf`);
        document.body.appendChild(link);
        link.click();
        link.remove();
      }
    } catch (err) {
      console.error("Employee Bulk PDF failed:", err);
      alert("Failed to generate bulk PDF for this employee.");
    } finally {
      setBulkPdfLoading(false);
    }
  };

  if (loading) return <div className="loading-spinner"><div className="spinner"></div></div>;
  if (!employee) return <div className="empty-state">Employee not found</div>;

  return (
    <div>
      <div style={{ marginBottom: '20px' }}>
        <Link to="/employees" className="btn btn-ghost" style={{ display: 'inline-flex', alignItems: 'center', gap: '8px' }}>
          <FiArrowLeft /> Back to Directory
        </Link>
      </div>

      <div className="card" style={{ marginBottom: '24px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '20px' }}>
          <div style={{ width: '64px', height: '64px', borderRadius: '50%', background: 'var(--gradient-primary)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '1.5rem', color: 'white', fontWeight: 'bold' }}>
            {employee.name.charAt(0)}
          </div>
          <div>
            <h2 style={{ fontSize: '1.5rem', marginBottom: '4px' }}>{employee.name}</h2>
            <div style={{ color: 'var(--text-muted)', fontSize: '0.85rem', display: 'flex', gap: '16px' }}>
              <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}><FiUser /> IPPIS: {employee.ippis_number} | File: {employee.file_no}</span>
              <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}><FiBriefcase /> {employee.department} - {employee.division}</span>
              <span className="badge badge-blue">GL {employee.gl}</span>
            </div>
          </div>
        </div>
      </div>

      {payslipHistory.length === 0 && jobHistory.length === 0 ? (
        <div className="card empty-state">
          <FiFileText className="empty-state-icon" />
          <h3>No Records Found</h3>
          <p>This employee has no payslip or job history records in the system.</p>
        </div>
      ) : (
        <>
          <div style={{ display: 'flex', gap: '16px', marginBottom: '24px', borderBottom: '1px solid var(--border-secondary)', paddingBottom: '8px' }}>
            <button 
              className={`btn ${activeTab === 'payslips' ? 'btn-primary' : 'btn-ghost'}`} 
              onClick={() => setActiveTab('payslips')}
            >
              Payslips
            </button>
            <button 
              className={`btn ${activeTab === 'history' ? 'btn-primary' : 'btn-ghost'}`} 
              onClick={() => setActiveTab('history')}
            >
              Job History
            </button>
          </div>

          {activeTab === 'payslips' && (
            <div style={{ display: 'flex', gap: '24px' }}>
          {/* Sidebar: Month Selector */}
          <div style={{ width: '240px', flexShrink: 0 }}>
            <div className="card" style={{ padding: '16px' }}>
              <h3 className="card-title">Payslip History</h3>
              
              <div style={{ marginTop: '12px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                <select className="form-select form-select-sm" value={filterYear} onChange={e => setFilterYear(e.target.value)}>
                  <option value="">All Years</option>
                  {availableYears.map(y => <option key={y} value={y}>{y}</option>)}
                </select>
                <select className="form-select form-select-sm" value={filterMonth} onChange={e => setFilterMonth(e.target.value)}>
                  <option value="">All Months</option>
                  {allMonths.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
                </select>
              </div>

              <div style={{ marginTop: '16px', display: 'flex', flexDirection: 'column', gap: '8px', paddingBottom: '16px', borderBottom: '1px solid var(--border-secondary)' }}>
                <button className="btn btn-sm btn-primary" onClick={() => handleEmployeeBulkPdf(true)} disabled={bulkPdfLoading}>
                  {bulkPdfLoading ? 'Loading...' : 'View All Filtered'}
                </button>
                <button className="btn btn-sm btn-secondary" onClick={() => handleEmployeeBulkPdf(false)} disabled={bulkPdfLoading}>
                  {bulkPdfLoading ? 'Loading...' : 'Download All Filtered'}
                </button>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginTop: '12px', maxHeight: '400px', overflowY: 'auto' }}>
                {filteredPayslips.length === 0 ? (
                  <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>No payslips match filters.</div>
                ) : (
                  filteredPayslips.map(p => (
                    <button 
                      key={p.id}
                      className={`btn ${selectedPayslipId === p.id ? 'btn-primary' : 'btn-secondary'}`}
                      style={{ width: '100%', justifyContent: 'flex-start' }}
                      onClick={() => setSelectedPayslipId(p.id)}
                    >
                      {formatMonthYear(p.month_year)}
                    </button>
                  ))
                )}
              </div>
            </div>
          </div>

          {/* Main Content: Full Payslip */}
          <div style={{ flex: 1 }}>
            {payslipLoading || !fullPayslip ? (
              <div className="card" style={{ height: '400px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <div className="spinner"></div>
              </div>
            ) : (
              <div className="card">
                <div className="card-header" style={{ borderBottom: '1px solid var(--border-secondary)', paddingBottom: '16px', marginBottom: '20px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%' }}>
                    <h2>Payslip for {formatMonthYear(fullPayslip.month_year)}</h2>
                    <div style={{ display: 'flex', gap: '8px' }}>
                      <button className="btn btn-secondary btn-sm" onClick={() => handleDownloadPdf(true)} disabled={pdfLoading}>
                        {pdfLoading ? 'Loading...' : 'View PDF'}
                      </button>
                      <button className="btn btn-primary btn-sm" onClick={() => handleDownloadPdf(false)} disabled={pdfLoading}>
                        {pdfLoading ? 'Loading...' : 'Download PDF'}
                      </button>
                    </div>
                  </div>
                  <div style={{ textAlign: 'right', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                    <div>Grade: {fullPayslip.grade} | Step: {fullPayslip.step}</div>
                    <div>Designation: {fullPayslip.designation}</div>
                  </div>
                </div>

                <div className="payslip-summary-grid">
                  <div className="payslip-summary-item earnings">
                    <div className="payslip-summary-amount">{formatCurrency(fullPayslip.total_gross_earnings)}</div>
                    <div className="payslip-summary-label">Gross Earnings</div>
                  </div>
                  <div className="payslip-summary-item deductions">
                    <div className="payslip-summary-amount">{formatCurrency(fullPayslip.total_gross_deductions)}</div>
                    <div className="payslip-summary-label">Gross Deductions</div>
                  </div>
                  <div className="payslip-summary-item net">
                    <div className="payslip-summary-amount">{formatCurrency(fullPayslip.total_net_earnings)}</div>
                    <div className="payslip-summary-label">Net Pay</div>
                  </div>
                </div>

                <div className="payslip-detail-grid">
                  {/* Earnings Table */}
                  <div>
                    <h3 className="card-title" style={{ color: 'var(--accent-emerald)', marginBottom: '12px' }}>Earnings Details</h3>
                    <table style={{ background: 'var(--bg-secondary)', borderRadius: 'var(--radius-md)' }}>
                      <tbody>
                        {fullPayslip.earnings.map(e => (
                          <tr key={e.id}>
                            <td style={{ fontSize: '0.8rem' }}>{e.earning_type}</td>
                            <td style={{ textAlign: 'right', fontWeight: 600, color: 'var(--accent-emerald)' }}>{formatCurrency(e.amount)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  {/* Deductions Table */}
                  <div>
                    <h3 className="card-title" style={{ color: 'var(--accent-rose)', marginBottom: '12px' }}>Deductions Details</h3>
                    <table style={{ background: 'var(--bg-secondary)', borderRadius: 'var(--radius-md)' }}>
                      <tbody>
                        {fullPayslip.deductions.map(d => (
                          <tr key={d.id}>
                            <td style={{ fontSize: '0.8rem' }}>{d.deduction_type}</td>
                            <td style={{ textAlign: 'right', fontWeight: 600, color: 'var(--accent-rose)' }}>{formatCurrency(d.amount)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* Bank & Pension Info */}
                <div style={{ marginTop: '32px', paddingTop: '20px', borderTop: '1px solid var(--border-secondary)', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px' }}>
                  <div>
                    <h4 style={{ fontSize: '0.8rem', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '8px' }}><FiCreditCard /> Bank Information</h4>
                    <div style={{ fontSize: '0.9rem' }}>
                      <div><span style={{ color: 'var(--text-muted)' }}>Bank:</span> {fullPayslip.bank_name || 'N/A'}</div>
                      <div><span style={{ color: 'var(--text-muted)' }}>Account:</span> {fullPayslip.account_number || 'N/A'}</div>
                    </div>
                  </div>
                  <div>
                    <h4 style={{ fontSize: '0.8rem', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '8px' }}>Pension Information</h4>
                    <div style={{ fontSize: '0.9rem' }}>
                      <div><span style={{ color: 'var(--text-muted)' }}>PFA:</span> {fullPayslip.pfa_name || 'N/A'}</div>
                      <div><span style={{ color: 'var(--text-muted)' }}>PIN:</span> {fullPayslip.pension_pin || 'N/A'}</div>
                    </div>
                  </div>
                </div>

              </div>
            )}
          </div>
        </div>
          )}

          {activeTab === 'history' && (
            <div className="card">
              <h3 className="card-title" style={{ marginBottom: '20px' }}>Promotion & Transfer History</h3>
              {jobHistory.length === 0 ? (
                <p style={{ color: 'var(--text-muted)' }}>No historical changes recorded for this employee.</p>
              ) : (
                <table style={{ background: 'var(--bg-secondary)', borderRadius: 'var(--radius-md)', width: '100%' }}>
                  <thead>
                    <tr>
                      <th style={{ textAlign: 'left', padding: '12px' }}>Date</th>
                      <th style={{ textAlign: 'left', padding: '12px' }}>Change Type</th>
                      <th style={{ textAlign: 'left', padding: '12px' }}>Previous</th>
                      <th style={{ textAlign: 'left', padding: '12px' }}>New</th>
                    </tr>
                  </thead>
                  <tbody>
                    {jobHistory.map(item => {
                      const dateObj = new Date(item.change_date);
                      const isPromotion = item.old_gl !== item.new_gl;
                      const isTransfer = item.old_department !== item.new_department || item.old_division !== item.new_division;
                      let changeType = "Update";
                      if (isPromotion && isTransfer) changeType = "Promotion & Transfer";
                      else if (isPromotion) changeType = "Promotion";
                      else if (isTransfer) changeType = "Transfer";

                      return (
                        <tr key={item.id} style={{ borderBottom: '1px solid var(--border-secondary)' }}>
                          <td style={{ padding: '12px' }}>{dateObj.toLocaleDateString()}</td>
                          <td style={{ padding: '12px' }}>
                            <span className={`badge ${isPromotion ? 'badge-blue' : 'badge-emerald'}`}>
                              {changeType}
                            </span>
                          </td>
                          <td style={{ padding: '12px', fontSize: '0.85rem' }}>
                            {item.old_gl && <div>GL: {item.old_gl}</div>}
                            {item.old_department && <div>Dept: {item.old_department}</div>}
                            {item.old_division && <div>Div: {item.old_division}</div>}
                          </td>
                          <td style={{ padding: '12px', fontSize: '0.85rem', fontWeight: 500 }}>
                            {item.new_gl && <div>GL: {item.new_gl}</div>}
                            {item.new_department && <div>Dept: {item.new_department}</div>}
                            {item.new_division && <div>Div: {item.new_division}</div>}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
