// Radio Recorder Custom Panel für Home Assistant
// Erstellt ein eigenes Dashboard als Unterseite

class RadioRecorderPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this.jobs = [];
  }

  async connectedCallback() {
    await this.loadJobs();
    this.render();
    // Aktualisiere alle 30 Sekunden
    this.interval = setInterval(() => this.loadJobs(), 30000);
  }

  disconnectedCallback() {
    if (this.interval) {
      clearInterval(this.interval);
    }
  }

  async loadJobs() {
    try {
      const response = await fetch('/api/hassio/addons/local_radio_recorder/info');
      const data = await response.json();
      this.jobs = data.data?.options?.jobs || [];
      this.render();
    } catch (error) {
      console.error('Fehler beim Laden der Jobs:', error);
      this.jobs = [];
    }
  }

  render() {
    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          padding: 20px;
          font-family: var(--mdc-typography-font-family, Roboto, sans-serif);
          background: var(--primary-background-color);
          min-height: 100vh;
        }
        .header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 30px;
          padding-bottom: 20px;
          border-bottom: 2px solid var(--divider-color);
        }
        .header h1 {
          margin: 0;
          color: var(--primary-text-color);
          font-size: 32px;
          display: flex;
          align-items: center;
          gap: 15px;
        }
        .header-icon {
          font-size: 40px;
        }
        .add-button {
          background: var(--primary-color);
          color: var(--text-primary-color);
          border: none;
          padding: 12px 24px;
          border-radius: 8px;
          cursor: pointer;
          font-size: 16px;
          font-weight: 500;
          box-shadow: 0 2px 4px rgba(0,0,0,0.2);
          transition: all 0.3s;
        }
        .add-button:hover {
          opacity: 0.9;
          box-shadow: 0 4px 8px rgba(0,0,0,0.3);
        }
        .jobs-list {
          display: grid;
          gap: 20px;
        }
        .job-card {
          background: var(--card-background-color);
          border-radius: 12px;
          padding: 24px;
          box-shadow: 0 2px 8px rgba(0,0,0,0.1);
          transition: all 0.3s;
        }
        .job-card:hover {
          box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        }
        .job-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 20px;
        }
        .job-name {
          font-size: 24px;
          font-weight: bold;
          color: var(--primary-text-color);
        }
        .job-actions {
          display: flex;
          gap: 10px;
        }
        .btn {
          padding: 10px 20px;
          border: none;
          border-radius: 6px;
          cursor: pointer;
          font-size: 14px;
          font-weight: 500;
          transition: all 0.2s;
        }
        .btn-edit {
          background: var(--accent-color);
          color: var(--text-primary-color);
        }
        .btn-edit:hover {
          opacity: 0.9;
        }
        .btn-delete {
          background: #f44336;
          color: white;
        }
        .btn-delete:hover {
          background: #d32f2f;
        }
        .job-details {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
          gap: 20px;
          margin-top: 20px;
        }
        .detail-item {
          display: flex;
          flex-direction: column;
          padding: 12px;
          background: var(--secondary-background-color);
          border-radius: 8px;
        }
        .detail-label {
          font-size: 12px;
          color: var(--secondary-text-color);
          margin-bottom: 6px;
          text-transform: uppercase;
          font-weight: 500;
        }
        .detail-value {
          font-size: 16px;
          color: var(--primary-text-color);
          word-break: break-word;
        }
        .empty-state {
          text-align: center;
          padding: 80px 20px;
          color: var(--secondary-text-color);
        }
        .empty-state-icon {
          font-size: 80px;
          margin-bottom: 20px;
        }
        .empty-state h2 {
          margin-bottom: 10px;
          color: var(--primary-text-color);
        }
        .empty-state p {
          margin-bottom: 30px;
        }
        .status-badge {
          display: inline-block;
          padding: 4px 12px;
          border-radius: 12px;
          font-size: 12px;
          font-weight: 500;
          margin-left: 10px;
        }
        .status-active {
          background: #4caf50;
          color: white;
        }
        .status-inactive {
          background: #9e9e9e;
          color: white;
        }
        .config-link {
          display: inline-block;
          margin-top: 20px;
          padding: 12px 24px;
          background: var(--primary-color);
          color: var(--text-primary-color);
          text-decoration: none;
          border-radius: 8px;
          font-weight: 500;
        }
        .config-link:hover {
          opacity: 0.9;
        }
      </style>
      <div class="header">
        <h1>
          <span class="header-icon">📻</span>
          Radio Recorder
        </h1>
        <button class="add-button" onclick="this.getRootNode().host.addJob()">
          + Neuen Job hinzufügen
        </button>
      </div>
      <div class="jobs-list">
        ${this.jobs.length === 0 ? this.renderEmptyState() : this.jobs.map((job, index) => this.renderJob(job, index)).join('')}
      </div>
    `;
  }

  renderEmptyState() {
    return `
      <div class="empty-state">
        <div class="empty-state-icon">📻</div>
        <h2>Keine Jobs konfiguriert</h2>
        <p>Fügen Sie einen neuen Job hinzu, um Radio-Aufnahmen zu planen.</p>
        <a href="/config/addons/dashboard/radio_recorder" class="config-link">
          Zur Konfiguration
        </a>
      </div>
    `;
  }

  renderJob(job, index) {
    const weekdays = job.weekdays && job.weekdays.length > 0 
      ? job.weekdays.join(', ') 
      : 'Alle Wochentage';
    const dateRange = job.date_start && job.date_end
      ? `${job.date_start} - ${job.date_end}`
      : 'Unbegrenzt';
    
    return `
      <div class="job-card">
        <div class="job-header">
          <div>
            <span class="job-name">${job.name || 'Unbenannter Job'}</span>
            <span class="status-badge ${this.isJobActive(job) ? 'status-active' : 'status-inactive'}">
              ${this.isJobActive(job) ? 'Aktiv' : 'Inaktiv'}
            </span>
          </div>
          <div class="job-actions">
            <button class="btn btn-edit" onclick="this.getRootNode().host.editJob(${index})">Bearbeiten</button>
            <button class="btn btn-delete" onclick="this.getRootNode().host.deleteJob(${index})">Löschen</button>
          </div>
        </div>
        <div class="job-details">
          <div class="detail-item">
            <div class="detail-label">Stream URL</div>
            <div class="detail-value">${job.stream_url || '-'}</div>
          </div>
          <div class="detail-item">
            <div class="detail-label">Startzeit</div>
            <div class="detail-value">${job.time_start || '-'}</div>
          </div>
          <div class="detail-item">
            <div class="detail-label">Endzeit</div>
            <div class="detail-value">${job.time_end || '-'}</div>
          </div>
          <div class="detail-item">
            <div class="detail-label">Speicherpfad</div>
            <div class="detail-value">${job.save_path || '/media/Musick (Standard)'}</div>
          </div>
          <div class="detail-item">
            <div class="detail-label">Wochentage</div>
            <div class="detail-value">${weekdays}</div>
          </div>
          <div class="detail-item">
            <div class="detail-label">Zeitraum</div>
            <div class="detail-value">${dateRange}</div>
          </div>
        </div>
      </div>
    `;
  }

  isJobActive(job) {
    // Einfache Prüfung ob Job aktiv ist
    if (!job.time_start) return false;
    const now = new Date();
    const currentTime = now.getHours() * 100 + now.getMinutes();
    const startTime = parseInt(job.time_start.replace(':', ''));
    return currentTime >= startTime;
  }

  addJob() {
    window.location.href = '/config/addons/dashboard/radio_recorder';
  }

  editJob(index) {
    window.location.href = '/config/addons/dashboard/radio_recorder';
  }

  async deleteJob(index) {
    if (confirm('Möchten Sie diesen Job wirklich löschen?')) {
      this.jobs.splice(index, 1);
      // Hier würde die Konfiguration aktualisiert werden
      // Für jetzt nur visuell entfernen
      this.render();
    }
  }
}

customElements.define('radio-recorder-panel', RadioRecorderPanel);

