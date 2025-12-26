"use client";

import { useState, useEffect, useCallback, useRef } from 'react';

// API-Base-URL aus Environment-Variable
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface PageInfo {
  id: string;
  url: string;
  status: number;
  sha256_text: string;
  title?: string;
  meta_description?: string;
  text_preview?: string;
  raw_download_url?: string;
  text_download_url?: string;
}

interface ErrorDetail {
  code: string;
  message: string;
}

interface ScanResult {
  ok: boolean;
  competitor_id?: string;
  snapshot_id?: string;
  pages?: PageInfo[];
  profile?: string;
  error?: ErrorDetail;
  snapshot_status?: string;
  progress?: { done: number; total: number };
}

interface SnapshotDetails {
  id: string;
  competitor_id: string;
  created_at: string;
  page_count: number;
  notes?: string;
  pages?: PageInfo[];
  status?: string;
  progress_pages_done?: number;
  progress_pages_total?: number;
  started_at?: string;
  finished_at?: string;
  error_code?: string;
  error_message?: string;
}

interface Competitor {
  id: string;
  name?: string;
  url: string;
  created_at: string;
  snapshots?: Array<{
    id: string;
    created_at: string;
    page_count: number;
    base_url?: string;
    notes?: string;
    status?: string;
    progress_pages_done?: number;
    progress_pages_total?: number;
  }>;
}

export default function Home() {
  const [url, setUrl] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [scanResult, setScanResult] = useState<ScanResult | null>(null);
  const [snapshotDetails, setSnapshotDetails] = useState<SnapshotDetails | null>(null);
  const [error, setError] = useState('');
  const [competitors, setCompetitors] = useState<Competitor[]>([]);
  const [isPolling, setIsPolling] = useState(false);
  const [currentProgress, setCurrentProgress] = useState<{ done: number; total: number } | null>(null);

  const abortControllerRef = useRef<AbortController | null>(null);

  // Lade alle Competitors beim ersten Laden
  useEffect(() => {
    loadCompetitors();
  }, []);

  // Status Polling für laufende Scans
  useEffect(() => {
    let intervalId: NodeJS.Timeout | null = null;

    if (isPolling && scanResult?.snapshot_id) {
      intervalId = setInterval(async () => {
        try {
          const response = await fetch(`${API_BASE_URL}/api/snapshots/${scanResult.snapshot_id}/status`);
          if (response.ok) {
            const statusData = await response.json();

            // Update Progress
            setCurrentProgress(statusData.progress);

            // Update ScanResult Progress
            setScanResult(prev => prev ? {
              ...prev,
              snapshot_status: statusData.status,
              progress: statusData.progress
            } : null);

            // Stoppe Polling wenn fertig oder fehlgeschlagen
            if (statusData.status === 'done' || statusData.status === 'failed') {
              setIsPolling(false);
              if (statusData.status === 'done') {
                // Lade finale Snapshot-Daten
                await loadSnapshotDetails(scanResult.snapshot_id);
              }
            }
          }
        } catch (err) {
          console.error('Fehler beim Status-Polling:', err);
          setIsPolling(false);
        }
      }, 2500); // Alle 2.5 Sekunden
    }

    return () => {
      if (intervalId) {
        clearInterval(intervalId);
      }
    };
  }, [isPolling, scanResult?.snapshot_id, loadSnapshotDetails]);

  // Cleanup bei Unmount
  useEffect(() => {
    return () => {
      abortControllerRef.current?.abort();
    };
  }, []);

  const loadCompetitors = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/competitors`);
      if (response.ok) {
        const data = await response.json();
        setCompetitors(data);
      }
    } catch (err) {
      console.error('Fehler beim Laden der Competitors:', err);
    }
  };

  // URL-Normalisierung wurde ins Backend verschoben

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    // Vorherigen Request abbrechen falls noch laufend
    abortControllerRef.current?.abort();
    abortControllerRef.current = new AbortController();

    setIsLoading(true);
    setError('');
    setScanResult(null);
    setSnapshotDetails(null);
    setIsPolling(false);
    setCurrentProgress(null);

    // URL wird jetzt im Backend normalisiert

    try {
      const response = await fetch(`${API_BASE_URL}/api/scan`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          name: null,
          url: url.trim(), // URL wird im Backend normalisiert
          llm: false, // Für jetzt ohne LLM
        }),
        signal: abortControllerRef.current.signal,
      });

      const result: ScanResult = await response.json();
      
      if (!result.ok) {
        // Fehler vom Backend (strukturiert)
        setScanResult(result);
        if (result.error) {
          setError(`${result.error.code}: ${result.error.message}`);
        } else {
          setError('Scan fehlgeschlagen');
        }
        return;
      }

      setScanResult(result);
      setCurrentProgress(result.progress || null);

      // Snapshot-Details laden, wenn verfügbar
      if (result.snapshot_id) {
        await loadSnapshotDetails(result.snapshot_id);

        // Starte Polling für laufende Scans
        if (result.snapshot_status === 'partial' || result.snapshot_status === 'running') {
          setIsPolling(true);
        }
      }

      // Competitors neu laden
      await loadCompetitors();
    } catch (err) {
      // Ignoriere Abbruch-Fehler
      if (err instanceof Error && err.name === 'AbortError') {
        return;
      }
      setError(err instanceof Error ? err.message : 'Unbekannter Fehler');
    } finally {
      setIsLoading(false);
    }
  };

  const loadSnapshotDetails = useCallback(async (snapshotId: string) => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/snapshots/${snapshotId}`);
      if (response.ok) {
        const details: SnapshotDetails = await response.json();
        setSnapshotDetails(details);
      } else {
        console.error('Fehler beim Laden der Snapshot-Details');
      }
    } catch (err) {
      console.error('Fehler beim Laden der Snapshot-Details:', err);
    }
  }, []);

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleString('de-DE');
  };

  return (
    <div className="container">
      <h1>Simple CompTool</h1>

      <form onSubmit={handleSubmit}>
        <div className="form-group">
          <input
            type="text"
            id="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="z.B. bild.de oder https://www.beispiel.de"
            required
            className="url-input"
          />
        </div>

        <button type="submit" disabled={isLoading}>
          {isLoading ? 'Scanne...' : 'Scan starten'}
        </button>
      </form>

      {error && (
        <div className="error">
          <strong>Fehler:</strong> {error}
        </div>
      )}

      {scanResult && (
        <div className="results">
          <h2>Scan-Ergebnis</h2>
          {scanResult.competitor_id && (
            <div className="result-item">
              <div className="result-label">Competitor ID:</div>
              <div className="result-value">{scanResult.competitor_id}</div>
            </div>
          )}
          {scanResult.snapshot_id && (
            <div className="result-item">
              <div className="result-label">Snapshot ID:</div>
              <div className="result-value">{scanResult.snapshot_id}</div>
            </div>
          )}
          <div className="result-item">
            <div className="result-label">Seiten gefunden:</div>
            <div className="result-value">{scanResult.pages?.length ?? 0}</div>
          </div>

          {scanResult.snapshot_status && (
            <div className="result-item">
              <div className="result-label">Status:</div>
              <div className="result-value">
                <span className={`status-badge ${scanResult.snapshot_status.toLowerCase()}`}>
                  {scanResult.snapshot_status}
                </span>
              </div>
            </div>
          )}

          {scanResult.progress && (
            <div className="result-item">
              <div className="result-label">Fortschritt:</div>
              <div className="result-value">
                <div className="progress-info">
                  {scanResult.progress.total > 0
                    ? `${scanResult.progress.done} / ${scanResult.progress.total} Seiten`
                    : '0 / 0 Seiten'
                  }
                  <div className="progress-bar">
                    <div
                      className="progress-fill"
                      style={{
                        width: `${scanResult.progress.total > 0
                          ? (scanResult.progress.done / scanResult.progress.total) * 100
                          : 0}%`
                      }}
                    />
                  </div>
                </div>
              </div>
            </div>
          )}

          {scanResult.profile && (
            <div className="result-item">
              <div className="result-label">LLM-Profil:</div>
              <div className="result-value profile-text">{scanResult.profile}</div>
            </div>
          )}

          {scanResult.error && (
            <div className="result-item error">
              <div className="result-label">Fehler:</div>
              <div className="result-value">
                <strong>{scanResult.error.code}:</strong> {scanResult.error.message}
              </div>
            </div>
          )}
        </div>
      )}

      {snapshotDetails && (
        <div className="snapshot-details">
          <h2>Snapshot-Details</h2>

          <div className="snapshot-status">
            <div className="status-info">
              <div className="status-item">
                <div className="status-label">Status</div>
                <div className={`status-value ${snapshotDetails.status?.toLowerCase() || 'unknown'}`}>
                  {snapshotDetails.status || 'Unknown'}
                </div>
              </div>
              <div className="status-item">
                <div className="status-label">Seiten</div>
                <div className="status-value">
                  {snapshotDetails.page_count}
                  {(snapshotDetails.progress_pages_done !== undefined && snapshotDetails.progress_pages_total !== undefined) &&
                    ` (${snapshotDetails.progress_pages_total > 0
                      ? `${snapshotDetails.progress_pages_done}/${snapshotDetails.progress_pages_total}`
                      : '0/0'
                    })`
                  }
                </div>
              </div>
              <div className="status-item">
                <div className="status-label">Erstellt</div>
                <div className="status-value">{formatDate(snapshotDetails.created_at)}</div>
              </div>
              {snapshotDetails.started_at && (
                <div className="status-item">
                  <div className="status-label">Gestartet</div>
                  <div className="status-value">{formatDate(snapshotDetails.started_at)}</div>
                </div>
              )}
              {snapshotDetails.finished_at && (
                <div className="status-item">
                  <div className="status-label">Fertig</div>
                  <div className="status-value">{formatDate(snapshotDetails.finished_at)}</div>
                </div>
              )}
            </div>
          </div>

          <div className="snapshot-info">
            <div className="info-item">
              <strong>Snapshot ID:</strong> {snapshotDetails.id}
            </div>
            {snapshotDetails.notes && (
              <div className="info-item">
                <strong>Notizen:</strong> {snapshotDetails.notes}
              </div>
            )}
            {snapshotDetails.error_message && (
              <div className="info-item error">
                <strong>Fehler:</strong> {snapshotDetails.error_message}
              </div>
            )}
          </div>

          <h3>Gefundene Seiten</h3>
          <div className="pages-table">
            <table>
              <thead>
                <tr>
                  <th>URL</th>
                  <th>Status</th>
                  <th>Titel</th>
                  <th>Hash</th>
                  <th>Text-Vorschau</th>
                  <th>Downloads</th>
                </tr>
              </thead>
              <tbody>
                {snapshotDetails.pages && snapshotDetails.pages.length > 0 ? (
                  snapshotDetails.pages.map((page) => (
                    <tr key={page.id}>
                      <td>
                        <a href={page.url} target="_blank" rel="noopener noreferrer">
                          {page.url}
                        </a>
                      </td>
                      <td>
                        <span className={`status ${page.status === 200 ? 'success' : 'error'}`}>
                          {page.status}
                        </span>
                      </td>
                      <td>{page.title || 'Kein Titel'}</td>
                      <td>
                        <code>{page.sha256_text.substring(0, 12)}...</code>
                      </td>
                      <td>
                        <div className="text-preview">
                          {page.text_preview ? (
                            <span>{page.text_preview}...</span>
                          ) : (
                            <span className="no-preview">Kein Text verfügbar</span>
                          )}
                        </div>
                      </td>
                      <td>
                        <div className="download-links">
                          {page.raw_download_url && (
                            <a
                              href={`${API_BASE_URL}${page.raw_download_url}`}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="download-link"
                            >
                              HTML
                            </a>
                          )}
                          {page.text_download_url && (
                            <a
                              href={`${API_BASE_URL}${page.text_download_url}`}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="download-link"
                            >
                              TXT
                            </a>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={6} style={{ textAlign: 'center', padding: '20px', color: '#666' }}>
                      Keine Seiten gefunden
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {competitors.length > 0 && (
        <div className="competitors-list">
          <h2>Gespeicherte Competitors</h2>
          {competitors.map((competitor) => (
            <div key={competitor.id} className="competitor-item">
              <h3>{competitor.name || 'Unbenannt'} ({competitor.url})</h3>
              <div style={{ fontSize: '14px', color: '#666', marginBottom: '10px' }}>
                Erstellt: {formatDate(competitor.created_at)}
              </div>

              <div className="snapshot-list">
                <strong>Snapshots:</strong>
                {competitor.snapshots && competitor.snapshots.length > 0 ? (
                  competitor.snapshots.map((snapshot) => (
                    <div
                      key={snapshot.id}
                      className="snapshot-item"
                      onClick={() => loadSnapshotDetails(snapshot.id)}
                      style={{ cursor: 'pointer', padding: '5px', borderRadius: '4px', transition: 'background-color 0.2s' }}
                      onMouseEnter={(e) => e.currentTarget.style.backgroundColor = '#f0f0f0'}
                      onMouseLeave={(e) => e.currentTarget.style.backgroundColor = 'transparent'}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <span>{formatDate(snapshot.created_at)} - {snapshot.page_count} Seiten</span>
                        {snapshot.status && (
                          <span className={`status-badge ${snapshot.status.toLowerCase()}`}>
                            {snapshot.status}
                          </span>
                        )}
                      </div>
                      {snapshot.base_url && <div style={{ fontSize: '12px', color: '#666', marginTop: '2px' }}>{snapshot.base_url}</div>}
                      {(snapshot.progress_pages_done !== undefined && snapshot.progress_pages_total !== undefined) && (
                        <div style={{ fontSize: '12px', color: '#666', marginTop: '2px' }}>
                          Progress: {snapshot.progress_pages_total > 0
                            ? `${snapshot.progress_pages_done}/${snapshot.progress_pages_total}`
                            : '0/0'
                          }
                        </div>
                      )}
                    </div>
                  ))
                ) : (
                  <div className="snapshot-item" style={{ fontStyle: 'italic', color: '#999' }}>
                    Keine Snapshots vorhanden
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
