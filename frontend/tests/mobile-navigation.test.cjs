const fs = require('node:fs'), path = require('node:path'), Module = require('node:module');
const ts = require('typescript'), React = require('react'), Renderer = require('react-test-renderer');
const test = require('node:test'), assert = require('node:assert/strict');
global.IS_REACT_ACT_ENVIRONMENT = true;
global.__DEV__ = false;
const { act } = React;
// Run the production auth provider, session and navigator with real React
// reconciliation. Native hosts/domain reads are local fixtures; no API writes.
const user = { id: 'a', display_name: 'Alex', timezone: 'Europe/London', status: 'ACTIVE', phone_e164: '+12025550198', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' };
const credentials = suffix => ({ access_token: 'access-' + suffix, refresh_token: 'refresh-' + suffix, token_type: 'Bearer', access_expires_at: new Date(Date.now() + 3600000).toISOString(), refresh_expires_at: new Date(Date.now() + 7200000).toISOString() });
function deferred() { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; }
function fixture(initial = credentials('old')) {
  let stored = initial, currentUser = user, auth, tree;
  const appListeners = new Set(), modules = new Map();
  const host = name => ({ children, ...props }) => React.createElement(name, props, children);
  const native = Object.fromEntries(['View', 'Text', 'Pressable', 'KeyboardAvoidingView', 'ScrollView', 'Modal'].map(name => [name, host(name)]));
  native.StyleSheet = { create: value => value };
  native.Platform = { OS: 'ios' };
  native.AppState = { addEventListener: (_, listener) => { appListeners.add(listener); return { remove: () => appListeners.delete(listener) }; } };
  const ui = Object.fromEntries(['Body', 'Button', 'EmptyState', 'LoadingState', 'Screen', 'Title', 'Amount', 'Card', 'ErrorState', 'PersonRow', 'StatusChip', 'TextField'].map(name => [name, host(name)]));
  const api = { getMe: async () => currentUser, refreshSession: async () => ({ ...credentials('rotated'), user: currentUser }), logout: async () => ({ logged_out: true }) };
  const store = { read: async () => stored, write: async value => { stored = { ...value }; }, clear: async () => { stored = null; } };
  const parent = { id: 'commitment', connection_id: 'connection', status: 'ACTIVE', type: 'IOU', principal_amount_minor: 10000, currency: 'INR', borrower: { id: 'a', display_name: 'Alex' }, lender: { id: 'b', display_name: 'Sam' }, creator: { id: 'a', display_name: 'Alex' } };
  const repayment = { id: 'repayment', commitment_id: parent.id, reported_by: parent.lender, amount_minor: 100, currency: 'INR', payment_date: '2026-10-01', reported_at: '2026-10-01T10:00:00Z', status: 'PENDING_VERIFICATION', note: null };
  function repaymentData() {
    return { data: { parent, rows: [repayment], detail: repayment, history: [] }, userId: 'a', fresh: true, busy: false, error: null,
      pending: () => null, refresh: async () => {}, actionBlocked: () => false, report: async () => null, decide: async () => null };
  }
  function load(relative) {
    const filename = path.resolve(__dirname, '..', relative);
    if (modules.has(filename)) return modules.get(filename).exports;
    const m = new Module(filename, module); m.filename = filename; m.paths = Module._nodeModulePaths(path.dirname(filename)); modules.set(filename, m);
    m.require = request => {
      if (request === 'react-native') return native;
      if (request === 'react-native-safe-area-context') return { SafeAreaView: host('SafeAreaView') };
      if (request.endsWith('/components/ui') || request === '../../components/ui') return ui;
      if (request.endsWith('/components/Brand')) return { Brand: host('Brand') };
      if (request.endsWith('/app/FoundationScreen')) return { FoundationScreen: host('FoundationScreen') };
      if (request.endsWith('/auth/AuthFlow')) return { AuthFlow: host('AuthFlow') };
      if (request.endsWith('/dashboard/Dashboard')) return { Activity: host('Activity'), Summary: host('Summary'), History: host('History') };
      if (request.endsWith('/dashboard/DueSummarySections')) return { DueSummaryOverview: host('DueSummaryOverview') };
      if (request.endsWith('/extensions/Extensions')) return { ExtensionsSection: host('ExtensionsSection'), NewExtension: host('NewExtension') };
      if (request.endsWith('/mutual-closure/MutualClosure')) return { MutualClosureSection: host('MutualClosureSection') };
      if (request.endsWith('/connections/Connections')) return { Connections: host('Connections') };
      if (request.endsWith('/notifications/Notifications')) return { Notifications: host('Notifications') };
      if (request.endsWith('/profile/Profile')) return { Profile: host('Profile') };
      if (request === './useCommitments') return { useCommitments: () => ({ data: { rows: [parent], detail: parent, terms: null }, userId: 'a', busy: false, error: null, pending: () => null, refresh: async () => {} }) };
      if (request === './useRepayments') return { useRepayments: repaymentData };
      if (request === './session/session-store') return { secureSessionStore: () => store };
      if (request === '@fides/shared/api/auth') return { createAuthApi: () => api };
      let source;
      if (request.startsWith('@fides/shared/')) source = path.resolve(__dirname, '../shared', request.slice('@fides/shared/'.length));
      else if (request.startsWith('.')) source = path.resolve(path.dirname(filename), request);
      if (source) {
        const target = [source + '.ts', source + '.tsx'].find(f => fs.existsSync(f));
        if (target) return load(path.relative(path.resolve(__dirname, '..'), target));
      }
      return require(request);
    };
    m._compile(ts.transpileModule(fs.readFileSync(filename, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText, filename);
    return m.exports;
  }
  const { AuthProvider, AuthContext } = load('mobile/features/auth/AuthProvider.tsx');
  const { RootNavigator } = load('mobile/navigation/RootNavigator.tsx');
  function Probe() { auth = React.useContext(AuthContext); return React.createElement(RootNavigator); }
  return {
    api, store, ApiError: load('shared/api/errors.ts').ApiError, stored: () => stored, session: () => auth.session, tree: () => tree,
    setUser: value => { currentUser = value; },
    mount: async () => { await act(async () => { tree = Renderer.create(React.createElement(AuthProvider, null, React.createElement(Probe))); }); },
    dispose: async () => { if (tree) await act(async () => tree.unmount()); },
    press: async title => { await act(async () => tree.root.findAll(n => n.type === 'Button' && n.props.title === title)[0].props.onPress()); },
    open: async page => {
      await act(async () => tree.root.findAll(n => n.type === 'Button' && n.props.title === 'View commitment with Sam')[0].props.onPress());
      if (page !== 'detail') await act(async () => tree.root.findAll(n => n.type === 'Button' && (page === 'report' ? n.props.title === 'Report repayment' : n.props.title?.startsWith('View repayment reported by Sam')))[0].props.onPress());
    },
    tab: async title => { await act(async () => tree.root.findAll(n => n.type === 'Pressable' && n.props.accessibilityRole === 'tab' && n.findByType('Text').children[0] === title)[0].props.onPress()); },
    input: async (label, value) => { await act(async () => tree.root.findByProps({ label }).props.onChangeText(value)); },
    field: label => tree.root.findAll(n => n.type === 'TextField' && n.props.label === label)[0].props.value,
    selected: () => tree.root.findAll(n => n.type === 'Pressable' && n.props.accessibilityState?.selected)[0]?.findByType('Text').children[0],
    title: title => tree.root.findAll(n => n.type === 'Title' && n.children[0] === title).length,
    resume: async () => { await act(async () => { for (const listener of appListeners) listener('background'); for (const listener of appListeners) listener('active'); }); },
    run: async fn => { await act(fn); },
  };
}
async function mounted(t, initial) { const f = fixture(initial); t.after(() => f.dispose()); await f.mount(); return f; }
async function pausedResume(f) { const pause = deferred(); f.api.getMe = () => pause.promise; await f.resume(); assert.equal(f.session().snapshot().status, 'loading'); return pause; }
function assertHidden(f) {
  const shell = f.tree().root.findAll(n => n.type === 'View' && n.props.importantForAccessibility === 'no-hide-descendants');
  assert.equal(shell.length, 1); assert.equal(shell[0].props.style.display, 'none'); assert.equal(shell[0].props.pointerEvents, 'none'); assert.equal(shell[0].props.accessibilityElementsHidden, true);
  assert.equal(f.tree().root.findAll(n => n.type === 'LoadingState' && n.props.message === 'Resolving your session…').length, 1);
}
test('mobile cold bootstrap renders no protected shell before /me succeeds', async t => {
  const f = fixture(); t.after(() => f.dispose()); const pause = deferred(); f.api.getMe = () => pause.promise; await f.mount();
  assert.equal(f.selected(), undefined); assert.equal(f.tree().root.findAll(n => n.type === 'Activity').length, 0);
  await f.run(async () => pause.resolve(user)); assert.equal(f.selected(), 'Home');
});
test('mobile AppState resume retains Activity after successful reconciliation', async t => {
  const f = await mounted(t); await f.tab('Activity'); const activity = f.tree().root.findByType('Activity'); const pause = await pausedResume(f); assertHidden(f);
  await f.run(async () => pause.resolve(user)); assert.equal(f.selected(), 'Activity'); assert.equal(f.tree().root.findByType('Activity'), activity);
});
for (const [page, title] of [['detail', 'Commitment detail'], ['repayment', 'Repayment detail']]) test('mobile resume retains nested ' + page + ' screen', async t => {
  const f = await mounted(t); await f.open(page); const pause = await pausedResume(f); assertHidden(f);
  await f.run(async () => pause.resolve(user)); assert.equal(f.title(title), 1);
});
test('mobile token rotation retains destination and replaces both live credentials', async t => {
  const f = await mounted(t); await f.tab('Activity'); const pause = deferred(); f.api.refreshSession = () => pause.promise;
  let operation; await f.run(async () => { operation = f.session().refresh(); }); assertHidden(f);
  await f.run(async () => { pause.resolve({ ...credentials('new'), user }); await operation; });
  assert.equal(f.selected(), 'Activity'); assert.equal(f.session().accessToken(), 'access-new'); assert.equal(f.stored().refresh_token, 'refresh-new');
});
test('mobile AppState resume rotates expired access before restoring Activity', async t => {
  const f = await mounted(t); await f.tab('Activity');
  await f.store.write({ ...f.stored(), access_expires_at: new Date(Date.now() - 1000).toISOString() });
  const pause = deferred(); f.api.refreshSession = () => pause.promise; await f.resume(); assertHidden(f);
  await f.run(async () => pause.resolve({ ...credentials('resumed'), user }));
  assert.equal(f.selected(), 'Activity'); assert.equal(f.session().accessToken(), 'access-resumed'); assert.equal(f.stored().refresh_token, 'refresh-resumed');
});
test('mobile real repayment draft and reviewed payload survive successful resume', async t => {
  const f = await mounted(t); await f.open('report'); await f.input('Amount (INR)', '12.34'); await f.input('Payment date', '2026-10-01'); await f.input('Note (optional)', 'Draft repayment');
  const pause = await pausedResume(f); assertHidden(f); await f.run(async () => pause.resolve(user));
  assert.equal(f.field('Amount (INR)'), '12.34'); assert.equal(f.field('Payment date'), '2026-10-01'); assert.equal(f.field('Note (optional)'), 'Draft repayment');
  await f.press('Review repayment'); const amount = f.tree().root.findByType('Amount'); assert.equal(amount.props.minor, 1234); assert.equal(amount.props.currency, 'INR');
  const again = await pausedResume(f); await f.run(async () => again.resolve(user)); assert.equal(f.tree().root.findByType('Amount').props.minor, 1234);
});
test('mobile native confirmation modal hides protected children while retaining decision note', async t => {
  const f = await mounted(t); await f.open('repayment'); await f.press('Verify repayment'); await f.input('Note (optional)', 'Decision draft');
  assert.equal(f.tree().root.findByType('Modal').props.visible, true); const pause = await pausedResume(f); assertHidden(f);
  assert.equal(f.tree().root.findByType('Modal').props.visible, false); assert.equal(f.tree().root.findByType('Modal').children.length, 0);
  await f.run(async () => pause.resolve(user)); assert.equal(f.tree().root.findByType('Modal').props.visible, true); assert.equal(f.field('Note (optional)'), 'Decision draft');
});
for (const code of ['REFRESH_TOKEN_EXPIRED', 'SESSION_REVOKED']) test('mobile ' + code + ' clears protected tree and returns safely to login', async t => {
  const f = await mounted(t); await f.tab('Activity'); const { ApiError } = f; const pause = deferred(); f.api.refreshSession = () => pause.promise;
  let operation; await f.run(async () => { operation = f.session().refresh(); }); assertHidden(f);
  await f.run(async () => { pause.reject(new ApiError(code, 'Please log in again.', 401)); await operation; });
  assert.equal(f.selected(), undefined); assert.equal(f.tree().root.findAll(n => n.type === 'Activity').length, 0); assert.equal(f.session().accessToken(), null); assert.equal(f.stored(), null);
  await f.run(async () => f.session().establish({ ...credentials('login'), user })); assert.equal(f.selected(), 'Home');
});
test('mobile actual logout discards drafts even if server logout fails', async t => {
  const f = await mounted(t); await f.open('report'); await f.input('Note (optional)', 'Discard me'); f.api.logout = async () => { throw new Error('network'); };
  await f.run(async () => f.session().logout()); assert.equal(f.selected(), undefined); assert.equal(f.stored(), null);
  await f.run(async () => f.session().establish({ ...credentials('login'), user })); assert.equal(f.selected(), 'Home'); await f.open('report'); assert.equal(f.field('Note (optional)'), '');
});
test('mobile logout followed immediately by same-account login still resets navigation', async t => {
  const f = await mounted(t); await f.open('report'); await f.input('Note (optional)', 'Discard between sessions');
  await f.run(async () => {
    await f.session().logout();
    await f.session().establish({ ...credentials('login'), user });
  });
  assert.equal(f.title('Home'), 1); await f.open('report'); assert.equal(f.field('Note (optional)'), '');
});
test('mobile account change remounts protected navigation and clears old repayment draft', async t => {
  const f = await mounted(t); await f.open('report'); await f.input('Note (optional)', 'Old account draft'); const other = { ...user, id: 'other', display_name: 'Sam' }; f.setUser(other);
  await f.run(async () => f.session().establish({ ...credentials('other'), user: other })); assert.equal(f.selected(), 'Home'); assert.equal(f.title('Home'), 1);
  await f.open('report'); assert.equal(f.field('Note (optional)'), '');
});
test('mobile failed reconciliation discards navigation even when credentials permit explicit recovery', async t => {
  const f = await mounted(t); await f.tab('Activity'); const pause = await pausedResume(f);
  await f.run(async () => pause.reject(new Error('network'))); assert.equal(f.selected(), undefined); assert.ok(f.stored());
  f.api.getMe = async () => user; await f.run(async () => f.session().bootstrap()); assert.equal(f.selected(), 'Home');
});
test('mobile revoked /me removes an open native modal and protected form', async t => {
  const f = await mounted(t); await f.open('repayment'); await f.press('Verify repayment'); await f.input('Note (optional)', 'Private decision');
  const pause = await pausedResume(f);
  await f.run(async () => pause.reject(new f.ApiError('SESSION_REVOKED', 'Please log in again.', 401)));
  assert.equal(f.session().snapshot().status, 'anonymous'); assert.equal(f.tree().root.findAll(n => n.type === 'Modal').length, 0);
  assert.equal(f.tree().root.findAll(n => n.type === 'TextField').length, 0); assert.equal(f.session().accessToken(), null);
});
