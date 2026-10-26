import test from 'node:test';
import assert from 'node:assert/strict';

// Test simulation of the exact asynchronous race condition in the client
test('Behavioral Race Test: Switching Organization A -> B while A is pending', async () => {
  let state = {
    org: null,
    isLoading: true,
    error: null,
  };

  let activeController = null;

  // Simulated fetchApi with delay
  async function mockFetchApi(orgId, options = {}) {
    return new Promise((resolve, reject) => {
      const delay = orgId === 'org-A' ? 100 : 20; // A is slow (100ms), B is fast (20ms)

      const timer = setTimeout(() => {
        if (options.signal?.aborted) {
          reject(new Error('Request was aborted'));
          return;
        }
        resolve({ id: orgId, name: `Organization ${orgId}` });
      }, delay);

      if (options.signal) {
        options.signal.addEventListener('abort', () => {
          clearTimeout(timer);
          reject(new Error('Request was aborted'));
        });
      }
    });
  }

  // Load function mirroring AdminOrganizationDetailPage / TenantOrganizationLayout
  async function loadOrganization(orgId) {
    if (activeController) {
      activeController.abort();
    }
    const controller = new AbortController();
    activeController = controller;
    const signal = controller.signal;

    // Reset state immediately on navigation
    state.org = null;
    state.isLoading = true;
    state.error = null;

    try {
      const data = await mockFetchApi(orgId, { signal });
      if (signal.aborted) return;
      state.org = data;
      state.isLoading = false;
    } catch (err) {
      if (signal.aborted || err.message === 'Request was aborted') {
        return; // Discard aborted request without error
      }
      state.error = err.message;
      state.isLoading = false;
    } finally {
      if (!signal.aborted) {
        state.isLoading = false;
      }
    }
  }

  // 1. Organization A request starts
  const promiseA = loadOrganization('org-A');
  assert.equal(state.isLoading, true, "State should be loading initially");
  assert.equal(state.org, null, "State should not have org initially");

  // 2. Navigation switches to Organization B while A is in flight (10ms later)
  await new Promise((r) => setTimeout(r, 10));
  const promiseB = loadOrganization('org-B');

  // Verify A was immediately reset
  assert.equal(state.org, null, "State must be reset immediately when switching to B");
  assert.equal(state.isLoading, true, "State must be in loading state for B");

  // 3. Wait for B's fast request to complete (20ms + 10ms = 30ms)
  await promiseB;

  assert.equal(state.isLoading, false, "Loading must be complete after B resolves");
  assert.notEqual(state.org, null, "B data must be present");
  assert.equal(state.org.id, 'org-B', "Active org must be org-B");
  assert.equal(state.error, null, "No error should be set");

  // 4. Wait until A's delayed request would have resolved (120ms total)
  await promiseA;

  // Verify A's late resolution did NOT overwrite B
  assert.equal(state.org.id, 'org-B', "A's late response must NOT overwrite B's state");
  assert.equal(state.isLoading, false, "A's abort must not alter B's loading state");
  assert.equal(state.error, null, "A's abort must not produce an error in B's workspace");
});
