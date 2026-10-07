import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { FiSearch, FiDownload, FiFilter, FiEye, FiLayers, FiArchive } from 'react-icons/fi';
import { employeesAPI, payslipsAPI, exportAPI } from '../api/client';
import { getErrorMessage, saveBlob, openPdfTab, safeFilename, formatMonthYear } from '../utils/download';

export default function Employees() {
  const navigate = useNavigate();
  const [employees, setEmployees] = useState([]);
  const [pagination, setPagination] = useState({ page: 1, per_page: 25, total: 0, pages: 0 });
  const [loading, setLoading] = useState(true);

  const [filters, setFilters] = useState({
    search: '',
    department: '',
    division: '',
    gl: ''
  });

  const [dropdowns, setDropdowns] = useState({ departments: [], divisions: [], glLevels: [], months: [] });
  const [bulkExportMonth, setBulkExportMonth] = useState('');

  // Key of the PDF/ZIP export currently being generated ('' when idle)
  const [exportBusy, setExportBusy] = useState('');
  const [showDeptPanel, setShowDeptPanel] = useState(false);
  const [deptPayslips, setDeptPayslips] = useState([]);
  const [deptLoading, setDeptLoading] = useState(false);
  const latestRequest = useRef(0);

  // Load dropdown data that does not depend on the filters
  useEffect(() => {
    const fetchDropdowns = async () => {
      try {
        const [deptRes, glRes, monthsRes] = await Promise.all([
          employeesAPI.departments(),
          employeesAPI.glLevels(),
          payslipsAPI.months()
        ]);
        setDropdowns(prev => ({
          ...prev,
          departments: deptRes.data.departments,
          glLevels: glRes.data.gl_levels,
          months: monthsRes.data.months
        }));
        if (monthsRes.data.months.length > 0) {
          setBulkExportMonth(monthsRes.data.months[0]);
        }
      } catch (err) {
        console.error("Failed to load dropdowns:", err);
      }
    };
    fetchDropdowns();
  }, []);

  // Divisions depend on the selected department
  useEffect(() => {
    employeesAPI.divisions(filters.department)
      .then(res => setDropdowns(prev => ({ ...prev, divisions: res.data.divisions })))
      .catch(err => console.error("Failed to load divisions:", err));
  }, [filters.department]);

  // Load employees
  useEffect(() => {
    fetchEmployees();
  }, [pagination.page, filters]);

  // Load the per-department payslip counts for the selected month
  useEffect(() => {
    if (!showDeptPanel || !bulkExportMonth) return;
    let cancelled = false;
    setDeptLoading(true);
    exportAPI.departmentPayslips(bulkExportMonth)
      .then(res => { if (!cancelled) setDeptPayslips(res.data.departments); })
      .catch(err => {
        console.error("Failed to load department payslips:", err);
        if (!cancelled) setDeptPayslips([]);
      })
      .finally(() => { if (!cancelled) setDeptLoading(false); });
    return () => { cancelled = true; };
  }, [showDeptPanel, bulkExportMonth]);

  const fetchEmployees = async () => {
    // Typing in the search box fires several requests; only the newest one may update the table
    const requestId = ++latestRequest.current;
    setLoading(true);
    try {
      const res = await employeesAPI.list({
        page: pagination.page,
        per_page: pagination.per_page,
        ...filters
      });
      if (requestId !== latestRequest.current) return;
      setEmployees(res.data.employees);
      setPagination(res.data.pagination);
    } catch (err) {
      console.error("Failed to load employees:", err);
    } finally {
      if (requestId === latestRequest.current) setLoading(false);
    }
  };

  const handleFilterChange = (e) => {
    const { name, value } = e.target;
    // A division belongs to one department, so changing department clears it
    setFilters(prev => ({ ...prev, [name]: value, ...(name === 'department' ? { division: '' } : {}) }));
    setPagination(prev => ({ ...prev, page: 1 }));
  };

  const handleGlMultiChange = (e) => {
    const options = e.target.options;
    const selectedValues = [];
    for (let i = 0; i < options.length; i++) {
      if (options[i].selected) {
        selectedValues.push(options[i].value);
      }
    }
    setFilters(prev => ({ ...prev, gl: selectedValues.join(',') }));
    setPagination(prev => ({ ...prev, page: 1 }));
  };

  const handleExport = async () => {
    try {
      const res = await exportAPI.employeesCSV(filters);
      saveBlob(new Blob([res.data]), 'employees_export.csv');
    } catch (err) {
      console.error("Export failed:", err);
      alert(await getErrorMessage(err, "Failed to export the employee list."));
    }
  };

  // Generate a merged payslip PDF for the selected month and either preview or download it
  const runPayslipPdf = async (key, params, filename, viewOnly) => {
    if (!bulkExportMonth) {
      alert("Please select a month first.");
      return;
    }
    const tab = viewOnly ? openPdfTab() : null;
    setExportBusy(key);
    try {
      const res = await exportAPI.bulkPayslipsPDF({ ...params, month_year: bulkExportMonth });
      const file = new Blob([res.data], { type: 'application/pdf' });
      if (viewOnly) {
        tab.show(file);
      } else {
        saveBlob(file, filename);
      }
    } catch (err) {
      console.error("Payslip PDF export failed:", err);
      tab?.close();
      alert(await getErrorMessage(err, "Failed to generate the payslip PDF. Ensure there are payslips for the selected month."));
    } finally {
      setExportBusy('');
    }
  };

  // Payslips of everyone matching the current filters
  const handleFilteredPdf = (viewOnly) => {
    const filename = filters.department
      ? `Payslips_${safeFilename(filters.department)}_${bulkExportMonth}.pdf`
      : `Bulk_Payslips_${bulkExportMonth}.pdf`;
    runPayslipPdf(viewOnly ? 'filtered:view' : 'filtered:download', filters, filename, viewOnly);
  };

  // Payslips of one whole department
  const handleDepartmentPdf = (dept, viewOnly) => {
    runPayslipPdf(
      `${dept.department}:${viewOnly ? 'view' : 'download'}`,
      { department: dept.department },
      `Payslips_${safeFilename(dept.label)}_${bulkExportMonth}.pdf`,
      viewOnly
    );
  };

  const handleAllDepartmentsZip = async () => {
    setExportBusy('zip');
    try {
      const res = await exportAPI.departmentPayslipsZip(bulkExportMonth);
      saveBlob(new Blob([res.data], { type: 'application/zip' }), `Department_Payslips_${bulkExportMonth}.zip`);
    } catch (err) {
      console.error("Department ZIP export failed:", err);
      alert(await getErrorMessage(err, "Failed to generate the department payslip PDFs."));
    } finally {
      setExportBusy('');
    }
  };

  const pdfScope = filters.department ? 'Department' : 'Bulk';

  return (
    <div>
      <div className="filter-panel">
        <div className="filter-panel-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '10px' }}>
          <h3><FiFilter /> Filters & Search</h3>
          <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
            <button className="btn btn-sm btn-secondary" onClick={handleExport}>
              <FiDownload /> Export CSV
            </button>
            <button className={`btn btn-sm ${showDeptPanel ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setShowDeptPanel(prev => !prev)}>
              <FiLayers /> Payslips by Department
            </button>
            <div style={{ display: 'flex', alignItems: 'center', gap: '5px', background: 'var(--bg-secondary)', padding: '2px', borderRadius: 'var(--radius-md)' }}>
              <select
                className="form-select"
                style={{ padding: '4px 8px', fontSize: '0.85rem', width: 'auto', border: 'none', background: 'transparent' }}
                value={bulkExportMonth}
                onChange={(e) => setBulkExportMonth(e.target.value)}
              >
                {dropdowns.months.map(m => <option key={m} value={m}>{formatMonthYear(m)}</option>)}
              </select>
              <button className="btn btn-sm btn-primary" onClick={() => handleFilteredPdf(true)} disabled={!!exportBusy} style={{ marginRight: '4px' }}>
                <FiEye /> {exportBusy === 'filtered:view' ? 'Preparing...' : `View ${pdfScope} PDF`}
              </button>
              <button className="btn btn-sm btn-primary" onClick={() => handleFilteredPdf(false)} disabled={!!exportBusy}>
                <FiDownload /> {exportBusy === 'filtered:download' ? 'Preparing...' : `Download ${pdfScope} PDF`}
              </button>
            </div>
          </div>
        </div>

        {showDeptPanel && (
          <div className="table-container" style={{ marginBottom: '20px' }}>
            <div className="table-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '10px' }}>
              <h3>Payslips by Department — {formatMonthYear(bulkExportMonth) || 'no month selected'}</h3>
              <button className="btn btn-sm btn-secondary" onClick={handleAllDepartmentsZip} disabled={!!exportBusy || deptPayslips.length === 0}>
                <FiArchive /> {exportBusy === 'zip' ? 'Preparing...' : 'Download All Departments (ZIP)'}
              </button>
            </div>
            {deptLoading ? (
              <div className="loading-spinner"><div className="spinner"></div></div>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Department</th>
                    <th>Payslips</th>
                    <th style={{ textAlign: 'right' }}>Payslip PDF</th>
                  </tr>
                </thead>
                <tbody>
                  {deptPayslips.length === 0 ? (
                    <tr><td colSpan="3" style={{ textAlign: 'center', padding: '24px' }}>No payslips found for this month</td></tr>
                  ) : (
                    deptPayslips.map(dept => (
                      <tr key={dept.department} style={{ cursor: 'default' }}>
                        <td style={{ fontWeight: 600 }}>{dept.label}</td>
                        <td>
                          {dept.payslips}
                          {dept.pdf_pages < dept.payslips && (
                            <span className="badge badge-amber" style={{ marginLeft: '8px' }}>
                              {dept.payslips - dept.pdf_pages} without PDF page
                            </span>
                          )}
                        </td>
                        <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
                          <button className="btn btn-sm btn-secondary" onClick={() => handleDepartmentPdf(dept, true)} disabled={!!exportBusy} style={{ marginRight: '6px' }}>
                            <FiEye /> {exportBusy === `${dept.department}:view` ? 'Preparing...' : 'View'}
                          </button>
                          <button className="btn btn-sm btn-primary" onClick={() => handleDepartmentPdf(dept, false)} disabled={!!exportBusy}>
                            <FiDownload /> {exportBusy === `${dept.department}:download` ? 'Preparing...' : 'Download PDF'}
                          </button>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            )}
          </div>
        )}

        <div className="filter-grid">
          <div className="form-group">
            <label className="form-label">Search (Name / File No / IPPIS)</label>
            <div className="search-bar" style={{ maxWidth: '100%' }}>
              <FiSearch className="search-icon" />
              <input
                type="text"
                name="search"
                value={filters.search}
                onChange={handleFilterChange}
                placeholder="Search..."
              />
            </div>
          </div>

          <div className="form-group">
            <label className="form-label">Department</label>
            <select name="department" className="form-select" value={filters.department} onChange={handleFilterChange}>
              <option value="">All Departments</option>
              {dropdowns.departments.map(d => <option key={d} value={d}>{d}</option>)}
            </select>
          </div>

          <div className="form-group">
            <label className="form-label">Division</label>
            <select name="division" className="form-select" value={filters.division} onChange={handleFilterChange}>
              <option value="">All Divisions</option>
              {dropdowns.divisions.map(d => <option key={d} value={d}>{d}</option>)}
            </select>
          </div>

          <div className="form-group">
            <label className="form-label">Grade Level (GL) - Hold Ctrl to select multiple</label>
            <select
              name="gl"
              className="form-select"
              multiple
              size="3"
              style={{ minHeight: '80px' }}
              value={filters.gl ? filters.gl.split(',') : []}
              onChange={handleGlMultiChange}
            >
              {dropdowns.glLevels.map(g => <option key={g} value={g}>{g}</option>)}
            </select>
          </div>
        </div>
      </div>

      <div className="table-container">
        <div className="table-header">
          <h3>Employees ({pagination.total})</h3>
        </div>

        {loading ? (
          <div className="loading-spinner"><div className="spinner"></div></div>
        ) : (
          <>
            <table>
              <thead>
                <tr>
                  <th>S/NO</th>
                  <th>File No</th>
                  <th>IPPIS Number</th>
                  <th>Name</th>
                  <th>GL</th>
                  <th>Department</th>
                  <th>Division</th>
                </tr>
              </thead>
              <tbody>
                {employees.length === 0 ? (
                  <tr><td colSpan="7" style={{ textAlign: 'center', padding: '24px' }}>No employees found</td></tr>
                ) : (
                  employees.map((emp, index) => (
                    <tr key={emp.id} onClick={() => navigate(`/employees/${emp.id}`)}>
                      <td>{(pagination.page - 1) * pagination.per_page + index + 1}</td>
                      <td>{emp.file_no}</td>
                      <td>{emp.ippis_number}</td>
                      <td style={{ fontWeight: 600 }}>{emp.name}</td>
                      <td>{emp.gl}</td>
                      <td>{emp.department}</td>
                      <td>{emp.division}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>

            {/* Pagination Controls */}
            {pagination.pages > 1 && (
              <div className="pagination">
                <div className="pagination-info">
                  Showing {(pagination.page - 1) * pagination.per_page + 1} to {Math.min(pagination.page * pagination.per_page, pagination.total)} of {pagination.total}
                </div>
                <div className="pagination-controls">
                  <button
                    className="pagination-btn"
                    disabled={!pagination.has_prev}
                    onClick={() => setPagination(prev => ({ ...prev, page: prev.page - 1 }))}
                  >
                    Previous
                  </button>
                  <span style={{ fontSize: '0.8rem', margin: '0 8px' }}>Page {pagination.page} of {pagination.pages}</span>
                  <button
                    className="pagination-btn"
                    disabled={!pagination.has_next}
                    onClick={() => setPagination(prev => ({ ...prev, page: prev.page + 1 }))}
                  >
                    Next
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
