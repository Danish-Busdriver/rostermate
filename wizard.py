from __future__ import annotations

FIRST_RUN_TEMPLATE = r'''
<!doctype html>
<html lang="da">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>RosterMate Setup</title>
    <style>
        :root {
            --primary: #2563EB;
            --secondary: #F5F7FA;
            --accent: #0EA5E9;
            --success: #22C55E;
            --error: #EF4444;
            --text: #111827;
            --muted: #6B7280;
            --panel: rgba(255, 255, 255, 0.84);
            --border: rgba(148, 163, 184, 0.28);
        }
        * { box-sizing: border-box; }
        body {
            margin: 0;
            min-height: 100vh;
            font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Segoe UI', sans-serif;
            background:
                radial-gradient(circle at top left, rgba(37, 99, 235, 0.12), transparent 24%),
                radial-gradient(circle at bottom right, rgba(14, 165, 233, 0.1), transparent 22%),
                linear-gradient(180deg, #fbfdff 0%, #eef3f9 100%);
            color: var(--text);
            display: grid;
            place-items: center;
            padding: 2rem;
        }
        .window {
            width: min(100%, 760px);
            background: var(--panel);
            backdrop-filter: blur(28px);
            border: 1px solid var(--border);
            border-radius: 30px;
            box-shadow: 0 35px 70px rgba(15, 23, 42, 0.12);
            overflow: hidden;
        }
        .window-top {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 0.9rem 1.2rem;
            border-bottom: 1px solid rgba(148, 163, 184, 0.18);
            background: rgba(255, 255, 255, 0.55);
        }
        .traffic {
            display: flex;
            gap: 0.45rem;
        }
        .traffic span {
            width: 12px;
            height: 12px;
            border-radius: 999px;
            display: inline-block;
        }
        .traffic span:nth-child(1) { background: #ff5f57; }
        .traffic span:nth-child(2) { background: #febc2e; }
        .traffic span:nth-child(3) { background: #28c840; }
        .window-top small { color: var(--muted); font-weight: 600; }
        .content { padding: 2.4rem; }
        .logo {
            width: 68px;
            height: 68px;
            border-radius: 18px;
            background: white;
            padding: 0.35rem;
            box-shadow: 0 18px 30px rgba(37, 99, 235, 0.12);
            margin-bottom: 1.35rem;
        }
        h1 {
            margin: 0 0 0.6rem;
            font-size: clamp(2rem, 4vw, 2.75rem);
            line-height: 1.04;
            letter-spacing: -0.03em;
        }
        .subtitle {
            margin: 0;
            color: var(--muted);
            font-size: 1.05rem;
            max-width: 56ch;
        }
        .info {
            margin-top: 1.5rem;
            padding: 1rem 1.1rem;
            border-radius: 18px;
            background: rgba(255, 255, 255, 0.72);
            border: 1px solid rgba(148, 163, 184, 0.18);
            color: var(--text);
            font-weight: 600;
        }
        .primary-button, .secondary-button {
            border: none;
            border-radius: 18px;
            padding: 1rem 1.25rem;
            font: inherit;
            font-weight: 700;
            cursor: pointer;
            min-width: 220px;
            transition: transform 0.18s ease, box-shadow 0.18s ease;
        }
        .primary-button:hover, .secondary-button:hover { transform: translateY(-1px); }
        .primary-button {
            background: linear-gradient(135deg, var(--primary), var(--accent));
            color: white;
            box-shadow: 0 20px 30px rgba(37, 99, 235, 0.22);
        }
        .secondary-button {
            background: white;
            color: var(--text);
            border: 1px solid rgba(148, 163, 184, 0.25);
        }
        .actions {
            display: flex;
            gap: 0.85rem;
            flex-wrap: wrap;
            margin-top: 2rem;
        }
        .error-box {
            margin-top: 1.3rem;
            padding: 1rem 1.1rem;
            border-radius: 18px;
            background: rgba(239, 68, 68, 0.09);
            border: 1px solid rgba(239, 68, 68, 0.18);
            color: #991b1b;
            display: none;
        }
        .error-box.visible { display: block; }
        .error-box ul {
            margin: 0.65rem 0 0;
            padding-left: 1rem;
        }
        .status-bar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 1rem;
            margin-top: 2rem;
            padding-top: 1rem;
            border-top: 1px solid rgba(148, 163, 184, 0.16);
            color: var(--muted);
        }
        .status-pill {
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            padding: 0.55rem 0.85rem;
            border-radius: 999px;
            background: rgba(255, 255, 255, 0.8);
            border: 1px solid rgba(148, 163, 184, 0.22);
            font-weight: 700;
        }
        .status-pill.connected { color: var(--success); }
        .status-pill.idle { color: var(--muted); }
        .status-pill.error { color: var(--error); }
        .progress {
            margin-top: 1.7rem;
            padding: 1rem 1.1rem;
            border-radius: 20px;
            background: rgba(255, 255, 255, 0.72);
            border: 1px solid rgba(148, 163, 184, 0.18);
            display: none;
        }
        .progress.visible { display: block; }
        .progress-line {
            display: flex;
            align-items: center;
            gap: 0.75rem;
            margin-top: 0.75rem;
            color: var(--muted);
            font-weight: 600;
        }
        .progress-line:first-child { margin-top: 0; }
        .spinner {
            width: 18px;
            height: 18px;
            border: 2px solid rgba(14, 165, 233, 0.2);
            border-top-color: var(--accent);
            border-radius: 999px;
            animation: spin 0.9s linear infinite;
            flex: 0 0 auto;
        }
        .checkmark { color: var(--success); font-size: 1rem; }
        .preview {
            margin-top: 1.4rem;
            display: none;
            gap: 0.85rem;
            grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
        }
        .preview.visible { display: grid; }
        .preview-card {
            padding: 1rem;
            border-radius: 18px;
            background: rgba(255, 255, 255, 0.82);
            border: 1px solid rgba(148, 163, 184, 0.18);
        }
        .preview-card strong { display: block; margin-bottom: 0.55rem; }
        .preview-card div { color: var(--muted); margin-top: 0.35rem; }
        .hidden { display: none !important; }
        @keyframes spin { to { transform: rotate(360deg); } }
        @media (max-width: 720px) {
            body { padding: 1rem; }
            .content { padding: 1.35rem; }
            .actions { flex-direction: column; }
            .primary-button, .secondary-button { width: 100%; }
            .status-bar { flex-direction: column; align-items: stretch; }
        }
    </style>
</head>
<body>
    <section class="window">
        <div class="window-top">
            <div class="traffic"><span></span><span></span><span></span></div>
            <small>RosterMate Setup</small>
        </div>
        <div class="content">
            <img class="logo" src="/static/Rostermate.png" alt="RosterMate logo">
            <div id="welcome-view" class="{{ 'hidden' if welcome_back else '' }}">
                <h1>Velkommen til RosterMate</h1>
                <p class="subtitle">Automatisk synkronisering af din vagtplan fra Tide SelfService.</p>
                <div class="info">🔒 Dine oplysninger bliver kun gemt lokalt på denne computer.</div>
                <div class="actions">
                    <button class="primary-button" id="connect-button" type="button">Forbind til SelfService</button>
                </div>
            </div>

            <div id="returning-view" class="{{ '' if welcome_back else 'hidden' }}">
                <h1>Velkommen tilbage</h1>
                <p class="subtitle">✓ Forbundet til SelfService</p>
                <div class="info">Sidste synkronisering: {{ last_sync }}</div>
                <div class="actions">
                    <a class="primary-button" href="{{ urls.dashboard_url }}" style="text-decoration:none; text-align:center;">Åbn Dashboard</a>
                    <button class="secondary-button" id="test-connection-button" type="button">Test forbindelse</button>
                    <button class="secondary-button" id="relogin-button" type="button">Log ind med en anden konto</button>
                </div>
            </div>

            <div id="error-box" class="error-box">
                <strong id="error-title">Forbindelsen kunne ikke gennemføres</strong>
                <div id="error-message" style="margin-top:0.4rem;"></div>
                <ul>
                    <li>Tjek at SelfService-vinduet blev åbnet og at login blev gennemført helt.</li>
                    <li>Prøv igen hvis Tide-sessionen er udløbet eller loginvinduet blev lukket for tidligt.</li>
                    <li>Hvis problemet fortsætter, brug “Log ind med en anden konto” for at nulstille sessionen.</li>
                </ul>
            </div>

            <div id="progress-box" class="progress">
                <div class="progress-line"><span class="checkmark" id="connected-check">○</span><span id="connected-text">Ikke forbundet</span></div>
                <div class="progress-line"><span class="spinner hidden" id="fetch-spinner"></span><span id="fetch-text">Henter dine vagter…</span></div>
                <div class="progress-line"><span class="spinner hidden" id="sync-spinner"></span><span id="sync-text">⟳ Synkroniserer…</span></div>
            </div>

            <div id="preview-grid" class="preview"></div>

            <div id="completion-actions" class="actions hidden">
                <button class="secondary-button" id="relogin-after-sync" type="button">Log ind igen</button>
                <a class="primary-button" id="continue-button" href="{{ urls.wizard_preferences_url }}" style="text-decoration:none; text-align:center;">Fortsæt</a>
            </div>

            <div class="status-bar">
                <small>{{ version }}</small>
                <span id="status-pill" class="status-pill {{ 'connected' if welcome_back else 'idle' }}">{{ 'Forbundet' if welcome_back else 'Ikke forbundet' }}</span>
            </div>
        </div>
    </section>

    <script>
        const connectButton = document.getElementById('connect-button');
        const reloginButton = document.getElementById('relogin-button');
        const reloginAfterSyncButton = document.getElementById('relogin-after-sync');
        const testConnectionButton = document.getElementById('test-connection-button');
        const progressBox = document.getElementById('progress-box');
        const statusPill = document.getElementById('status-pill');
        const connectedCheck = document.getElementById('connected-check');
        const connectedText = document.getElementById('connected-text');
        const fetchSpinner = document.getElementById('fetch-spinner');
        const fetchText = document.getElementById('fetch-text');
        const syncSpinner = document.getElementById('sync-spinner');
        const syncText = document.getElementById('sync-text');
        const previewGrid = document.getElementById('preview-grid');
        const completionActions = document.getElementById('completion-actions');
        const errorBox = document.getElementById('error-box');
        const errorMessage = document.getElementById('error-message');
        let activeFlowId = null;

        async function postJson(url) {
            const response = await fetch(url, { method: 'POST' });
            return response.json();
        }

        function showError(message) {
            errorMessage.textContent = message;
            errorBox.classList.add('visible');
        }

        function clearError() {
            errorBox.classList.remove('visible');
            errorMessage.textContent = '';
        }

        function showProgress() {
            progressBox.classList.add('visible');
            fetchSpinner.classList.remove('hidden');
            syncSpinner.classList.remove('hidden');
        }

        function renderPreview(preview) {
            previewGrid.innerHTML = '';
            for (const day of preview) {
                const card = document.createElement('article');
                card.className = 'preview-card';
                const title = document.createElement('strong');
                title.textContent = day.weekday;
                card.appendChild(title);
                for (const item of day.items) {
                    const line = document.createElement('div');
                    line.innerHTML = `<div>${item.title}</div><div>${item.time_label}</div>`;
                    card.appendChild(line);
                }
                previewGrid.appendChild(card);
            }
            previewGrid.classList.add('visible');
        }

        async function startLogin(resetSession = false) {
            clearError();
            completionActions.classList.add('hidden');
            previewGrid.classList.remove('visible');
            previewGrid.innerHTML = '';
            statusPill.textContent = 'Forbinder…';
            statusPill.className = 'status-pill idle';
            showProgress();
            connectedCheck.textContent = '○';
            connectedText.textContent = 'Åbner SelfService…';
            fetchText.textContent = 'Henter dine vagter…';
            syncText.textContent = '⟳ Synkroniserer…';
            const query = resetSession ? '?reset=1' : '';
            const result = await postJson('{{ urls.wizard_connect_url }}' + query);
            if (result.status !== 'ok') {
                statusPill.textContent = result.message || 'Fejl';
                statusPill.className = 'status-pill error';
                showError(result.message || 'Wizard-login kunne ikke startes.');
                return;
            }
            activeFlowId = result.flow_id;
            pollStatus();
        }

        async function testConnection() {
            clearError();
            statusPill.textContent = 'Tester…';
            statusPill.className = 'status-pill idle';
            const result = await postJson('{{ urls.wizard_test_connection_url }}');
            if (result.status === 'ok') {
                statusPill.textContent = 'Forbundet';
                statusPill.className = 'status-pill connected';
                connectedCheck.textContent = '✅';
                connectedText.textContent = result.message;
                return;
            }
            statusPill.textContent = 'Fejl';
            statusPill.className = 'status-pill error';
            showError(result.message || 'Forbindelsen kunne ikke bekræftes.');
        }

        async function pollStatus() {
            if (!activeFlowId) {
                return;
            }
            const response = await fetch(`{{ urls.wizard_status_url }}?flow_id=${activeFlowId}`);
            const data = await response.json();
            if (data.state === 'awaiting_login' || data.state === 'browser_open' || data.state === 'launching') {
                connectedText.textContent = data.message;
                setTimeout(pollStatus, 1200);
                return;
            }
            if (data.state === 'connected') {
                connectedCheck.textContent = '✅';
                connectedText.textContent = 'Forbundet';
                fetchText.textContent = 'Henter dine vagter…';
                syncText.textContent = '⟳ Synkroniserer…';
                statusPill.textContent = 'Forbundet';
                statusPill.className = 'status-pill connected';
                setTimeout(pollStatus, 1200);
                return;
            }
            if (data.state === 'syncing') {
                connectedCheck.textContent = '✅';
                connectedText.textContent = 'Forbundet';
                fetchText.textContent = 'Henter dine vagter…';
                syncText.textContent = data.message;
                statusPill.textContent = 'Synkroniserer…';
                statusPill.className = 'status-pill connected';
                setTimeout(pollStatus, 1200);
                return;
            }
            if (data.state === 'synced') {
                connectedCheck.textContent = '✅';
                connectedText.textContent = 'Forbundet';
                fetchSpinner.classList.add('hidden');
                syncSpinner.classList.add('hidden');
                fetchText.textContent = `✓ ${data.count} vagter fundet`;
                syncText.textContent = data.message;
                statusPill.textContent = 'Klar';
                statusPill.className = 'status-pill connected';
                renderPreview(data.preview || []);
                completionActions.classList.remove('hidden');
                return;
            }
            statusPill.textContent = data.message || 'Fejl';
            statusPill.className = 'status-pill error';
            connectedText.textContent = data.message || 'Fejl under login';
            fetchSpinner.classList.add('hidden');
            syncSpinner.classList.add('hidden');
            showError(data.message || 'Der opstod en fejl under loginforløbet.');
        }

        connectButton?.addEventListener('click', () => startLogin(false));
        testConnectionButton?.addEventListener('click', () => testConnection());
        reloginButton?.addEventListener('click', () => startLogin(true));
        reloginAfterSyncButton?.addEventListener('click', () => startLogin(true));
    </script>
</body>
</html>
'''


WIZARD_PREFERENCES_TEMPLATE = r'''
<!doctype html>
<html lang="da">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>RosterMate Setup</title>
    <style>
        :root {
            --primary: #2563EB;
            --secondary: #F5F7FA;
            --accent: #0EA5E9;
            --success: #22C55E;
            --error: #EF4444;
            --text: #111827;
            --muted: #6B7280;
            --panel: rgba(255, 255, 255, 0.9);
            --border: rgba(148, 163, 184, 0.28);
        }
        * { box-sizing: border-box; }
        body {
            margin: 0;
            min-height: 100vh;
            font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Segoe UI', sans-serif;
            background: linear-gradient(180deg, #fbfdff 0%, #eef3f9 100%);
            color: var(--text);
            display: grid;
            place-items: center;
            padding: 2rem;
        }
        .window {
            width: min(100%, 840px);
            background: var(--panel);
            border: 1px solid var(--border);
            border-radius: 30px;
            box-shadow: 0 35px 70px rgba(15, 23, 42, 0.12);
            overflow: hidden;
        }
        .content { padding: 2.3rem; }
        h1 { margin: 0 0 0.45rem; font-size: 2.35rem; letter-spacing: -0.03em; }
        .subtitle { margin: 0; color: var(--muted); }
        .layout { display: grid; grid-template-columns: minmax(0, 1.25fr) minmax(260px, 0.9fr); gap: 1.2rem; margin-top: 1.5rem; }
        .panel { padding: 1.2rem; border-radius: 22px; background: white; border: 1px solid var(--border); }
        .field { margin-top: 0.95rem; }
        .field label { display: block; margin-bottom: 0.35rem; color: var(--muted); font-size: 0.92rem; }
        .field input { width: 100%; padding: 0.9rem 1rem; border-radius: 14px; border: 1px solid var(--border); font: inherit; }
        .check { display: flex; gap: 0.7rem; align-items: flex-start; margin-top: 0.9rem; }
        .check input { margin-top: 0.2rem; }
        .preview-card { margin-top: 0.9rem; padding: 0.9rem; border-radius: 16px; background: var(--secondary); }
        .preview-card strong { display: block; margin-bottom: 0.45rem; }
        .test-status {
            margin-top: 0.9rem;
            padding: 0.9rem 1rem;
            border-radius: 16px;
            background: rgba(255, 255, 255, 0.82);
            border: 1px solid var(--border);
            color: var(--muted);
            display: none;
        }
        .test-status.visible { display: block; }
        .actions { display: flex; justify-content: space-between; gap: 0.8rem; margin-top: 1.5rem; }
        .primary-button, .secondary-link {
            border-radius: 18px; padding: 1rem 1.2rem; font: inherit; font-weight: 700; text-decoration: none; display: inline-flex; align-items: center; justify-content: center;
        }
        .primary-button { border: none; background: linear-gradient(135deg, var(--primary), var(--accent)); color: white; cursor: pointer; }
        .secondary-link { background: white; color: var(--text); border: 1px solid var(--border); }
        @media (max-width: 760px) {
            body { padding: 1rem; }
            .content { padding: 1.35rem; }
            .layout { grid-template-columns: 1fr; }
            .actions { flex-direction: column; }
        }
    </style>
</head>
<body>
    <section class="window">
        <div class="content">
            <h1>Kalenderindstillinger</h1>
            <p class="subtitle">Vælg hvordan dine vagter skal gemmes og vises efter første synkronisering.</p>
            <form method="post" action="{{ urls.wizard_complete_url }}">
                <div class="layout">
                    <div class="panel">
                        <div class="field">
                            <label for="calendar_name">Kalendernavn</label>
                            <input id="calendar_name" name="calendar_name" value="{{ settings.calendar_name }}">
                        </div>
                        <div class="field">
                            <label for="days_ahead">Antal dage frem</label>
                            <input id="days_ahead" name="days_ahead" type="number" min="1" max="30" value="{{ settings.days_ahead }}">
                        </div>
                        <label class="check"><input type="checkbox" name="keep_old_shifts" value="true" {% if settings.keep_old_shifts %}checked{% endif %}><span>Behold gamle vagter</span></label>
                        <label class="check"><input type="checkbox" name="launch_at_login" value="true" {% if settings.launch_at_login %}checked{% endif %}><span>Start automatisk med macOS</span></label>
                        <label class="check"><input type="checkbox" name="show_menu_bar_icon" value="true" {% if settings.show_menu_bar_icon %}checked{% endif %}><span>Vis ikon i menulinjen</span></label>
                        <label class="check"><input type="checkbox" name="notify_on_changes" value="true" {% if settings.notify_on_changes %}checked{% endif %}><span>Giv besked ved ændringer</span></label>
                    </div>
                    <aside class="panel">
                        <strong>Første synkronisering</strong>
                        <div class="preview-card">✅ Forbundet</div>
                        <div class="preview-card">✓ {{ preview_count }} vagter fundet</div>
                        {% for day in preview %}
                        <div class="preview-card">
                            <strong>{{ day.weekday }}</strong>
                            {% for item in day.items %}
                            <div>{{ item.title }}</div>
                            <div style="color: var(--muted); margin-top: 0.2rem;">{{ item.time_label }}</div>
                            {% endfor %}
                        </div>
                        {% endfor %}
                        <button class="secondary-link" id="test-connection-button" type="button" style="margin-top:1rem;">Test forbindelse</button>
                        <div id="test-status" class="test-status"></div>
                    </aside>
                </div>
                <div class="actions">
                    <a class="secondary-link" href="{{ urls.wizard_url }}">Tilbage</a>
                    <button class="primary-button" type="submit">Færdiggør</button>
                </div>
            </form>
        </div>
    </section>
    <script>
        const testButton = document.getElementById('test-connection-button');
        const testStatus = document.getElementById('test-status');

        async function runConnectionTest() {
            testStatus.classList.add('visible');
            testStatus.textContent = 'Tester forbindelsen til SelfService…';
            const response = await fetch('{{ urls.wizard_test_connection_url }}', { method: 'POST' });
            const data = await response.json();
            testStatus.textContent = data.message || 'Ukendt svar';
            testStatus.style.color = data.status === 'ok' ? '#166534' : '#991b1b';
            testStatus.style.background = data.status === 'ok' ? 'rgba(34, 197, 94, 0.10)' : 'rgba(239, 68, 68, 0.10)';
            testStatus.style.borderColor = data.status === 'ok' ? 'rgba(34, 197, 94, 0.18)' : 'rgba(239, 68, 68, 0.18)';
        }

        testButton?.addEventListener('click', runConnectionTest);
    </script>
</body>
</html>
'''
