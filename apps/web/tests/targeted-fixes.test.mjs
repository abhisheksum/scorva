import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB_ROOT = path.resolve(__dirname, '../src');

test('Fix 1: OrgRole type definition does not contain unsupported roles', () => {
  const apiTypesPath = path.join(WEB_ROOT, 'types/api.ts');
  const apiTypesContent = fs.readFileSync(apiTypesPath, 'utf8');

  // Verify OrgRole definition
  const roleMatch = apiTypesContent.match(/export type OrgRole = ([^;]+);/);
  assert.ok(roleMatch, 'OrgRole type definition should exist in types/api.ts');
  
  const roleDef = roleMatch[1];
  assert.ok(roleDef.includes("'org_owner'"), "OrgRole must include 'org_owner'");
  assert.ok(roleDef.includes("'org_admin'"), "OrgRole must include 'org_admin'");
  assert.ok(roleDef.includes("'organizer'"), "OrgRole must include 'organizer'");
  assert.ok(!roleDef.includes("'judge'"), "OrgRole must NOT contain 'judge'");
  assert.ok(!roleDef.includes("'mentor'"), "OrgRole must NOT contain 'mentor'");
});

test('Fix 1: Admin organization detail page does not offer judge or mentor in member dropdowns', () => {
  const pagePath = path.join(WEB_ROOT, 'app/admin/organizations/[organizationId]/page.tsx');
  const pageContent = fs.readFileSync(pagePath, 'utf8');

  // Verify formatRole does not include judge or mentor
  assert.ok(!pageContent.includes("case 'judge':"), "formatRole must not contain case 'judge'");
  assert.ok(!pageContent.includes("case 'mentor':"), "formatRole must not contain case 'mentor'");

  // Verify select options in page
  assert.ok(!pageContent.includes('value="judge"'), 'No select option with value="judge" allowed');
  assert.ok(!pageContent.includes('value="mentor"'), 'No select option with value="mentor" allowed');
});

test('Fix 2: Admin organization detail page resets tenant state and uses AbortController on orgId change', () => {
  const pagePath = path.join(WEB_ROOT, 'app/admin/organizations/[organizationId]/page.tsx');
  const pageContent = fs.readFileSync(pagePath, 'utf8');

  // Must use AbortController
  assert.ok(pageContent.includes('new AbortController()'), 'Must instantiate AbortController');
  assert.ok(pageContent.includes('abortControllerRef.current.abort()'), 'Must abort prior in-flight request on re-render / orgId change');
  
  // Must reset state immediately
  assert.ok(pageContent.includes('setOrg(null)'), 'Must immediately clear org state');
  assert.ok(pageContent.includes('setMembers([])'), 'Must immediately clear members state');
  assert.ok(pageContent.includes('setHackathons([])'), 'Must immediately clear hackathons state');
  assert.ok(pageContent.includes('setAuditEvents([])'), 'Must immediately clear audit events state');
  assert.ok(pageContent.includes('setIsLoading(true)'), 'Must set isLoading to true');

  // Must guard against late responses from aborted requests
  assert.ok(pageContent.includes('if (signal.aborted) return'), 'Must guard against setting state from aborted requests');

  // Skeleton guard must be (isLoading || !org || isStale)
  assert.ok(pageContent.includes('isLoading || !org'), 'Loading check must guard against rendering with missing or pending org');
  assert.ok(pageContent.includes('isStale'), 'Must guard against rendering stale organization data across navigations');
});

test('Fix 2: Tenant organization layout and pages reset tenant state and cancel on orgId change', () => {
  const layoutPath = path.join(WEB_ROOT, 'app/organizations/[organizationId]/layout.tsx');
  const layoutContent = fs.readFileSync(layoutPath, 'utf8');
  assert.ok(layoutContent.includes('new AbortController()'), 'Layout must use AbortController');
  assert.ok(layoutContent.includes('setOrg(null)'), 'Layout must clear org state immediately on orgId change');

  const profilePagePath = path.join(WEB_ROOT, 'app/organizations/[organizationId]/page.tsx');
  const profileContent = fs.readFileSync(profilePagePath, 'utf8');
  assert.ok(profileContent.includes('new AbortController()'), 'Tenant profile page must use AbortController');
  assert.ok(profileContent.includes('setOrg(null)'), 'Tenant profile page must clear org state immediately on orgId change');

  const hackathonsPagePath = path.join(WEB_ROOT, 'app/organizations/[organizationId]/hackathons/page.tsx');
  const hackathonsContent = fs.readFileSync(hackathonsPagePath, 'utf8');
  assert.ok(hackathonsContent.includes('new AbortController()'), 'Tenant hackathons page must use AbortController');
  assert.ok(hackathonsContent.includes('setHackathons([])'), 'Tenant hackathons page must clear hackathons state immediately on orgId change');
});

test('Fix 3: Audit event authorization 403 displays restricted notice honestly', () => {
  const pagePath = path.join(WEB_ROOT, 'app/admin/organizations/[organizationId]/page.tsx');
  const pageContent = fs.readFileSync(pagePath, 'utf8');

  // Verify 403 handling
  assert.ok(pageContent.includes('auditErr.status === 403'), 'Must check for audit 403 forbidden status');
  assert.ok(pageContent.includes('setAuditAccessDenied(true)'), 'Must set auditAccessDenied to true on 403');
  
  // Verify UI displays access restricted banner
  assert.ok(pageContent.includes('Audit Log Access Restricted'), 'Must render dedicated Audit Log Access Restricted notice');
  assert.ok(
    pageContent.includes('requires Security Administrator or Platform Owner privileges'),
    'Must explain required privileges without exposing sensitive logs'
  );
});

test('Fix 2 & 3: ApiClientError handles REQUEST_ABORTED and passes options.signal', () => {
  const clientPath = path.join(WEB_ROOT, 'lib/api-client.ts');
  const clientContent = fs.readFileSync(clientPath, 'utf8');

  assert.ok(clientContent.includes("'REQUEST_ABORTED'"), 'ApiClientError must throw REQUEST_ABORTED when signal is aborted');
  assert.ok(clientContent.includes('options?: RequestInit'), 'Client methods must accept optional RequestInit options');
});

test('Users & Access Admin: UsersPage implements server pagination, AbortController, and debounced filters', () => {
  const usersPagePath = path.join(WEB_ROOT, 'app/admin/users/page.tsx');
  const content = fs.readFileSync(usersPagePath, 'utf8');

  // Verify AbortController usage
  assert.ok(content.includes('new AbortController()'), 'UsersPage must use AbortController');
  assert.ok(content.includes('abortControllerRef.current.abort()'), 'UsersPage must cancel in-flight queries');

  // Verify pagination state and UI controls
  assert.ok(content.includes('totalPages'), 'UsersPage must handle totalPages');
  assert.ok(content.includes('limit'), 'UsersPage must configure a query limit');
  assert.ok(content.includes('ChevronLeft'), 'UsersPage must have previous page button');
  assert.ok(content.includes('ChevronRight'), 'UsersPage must have next page button');

  // Verify server-side paginated API call
  assert.ok(content.includes('api.getUsers'), 'UsersPage must call api.getUsers');
  assert.ok(content.includes('signal'), 'UsersPage must pass abort signal to api.getUsers');

  // Verify PaginatedUsersResponse in types
  const apiTypesPath = path.join(WEB_ROOT, 'types/api.ts');
  const apiTypesContent = fs.readFileSync(apiTypesPath, 'utf8');
  assert.ok(apiTypesContent.includes('interface PaginatedUsersResponse'), 'types/api.ts must define PaginatedUsersResponse');
});

test('Admin Sidebar: includes Support, Notifications, and Roles & Permissions navigation', () => {
  const sidebarPath = path.join(WEB_ROOT, 'components/admin/AdminSidebar.tsx');
  const sidebarContent = fs.readFileSync(sidebarPath, 'utf8');

  // Verify Roles & Permissions navigation item
  assert.ok(sidebarContent.includes("href: '/admin/roles-permissions'"), 'Sidebar must have /admin/roles-permissions route');
  assert.ok(sidebarContent.includes("title: 'Roles & Permissions'"), 'Sidebar must have Roles & Permissions title');
  assert.ok(sidebarContent.includes('ShieldCheck'), 'Sidebar must import and use ShieldCheck icon');

  // Verify Support Center navigation item
  assert.ok(sidebarContent.includes("href: '/admin/support'"), 'Sidebar must have /admin/support route');
  assert.ok(sidebarContent.includes("title: 'Support Center'"), 'Sidebar must have Support Center title');
  assert.ok(sidebarContent.includes('LifeBuoy'), 'Sidebar must import and use LifeBuoy icon');

  // Verify Notifications navigation item
  assert.ok(sidebarContent.includes("href: '/admin/notifications'"), 'Sidebar must have /admin/notifications route');
  assert.ok(sidebarContent.includes("title: 'Notifications'"), 'Sidebar must have Notifications title');
  assert.ok(sidebarContent.includes('Bell'), 'Sidebar must import and use Bell icon');

  // Verify target page files exist
  assert.ok(fs.existsSync(path.join(WEB_ROOT, 'app/admin/roles-permissions/page.tsx')), 'Roles & permissions page must exist');
  assert.ok(fs.existsSync(path.join(WEB_ROOT, 'app/admin/roles/page.tsx')), 'Roles redirect page must exist');
  assert.ok(fs.existsSync(path.join(WEB_ROOT, 'app/admin/support/page.tsx')), 'Support page must exist');
  assert.ok(fs.existsSync(path.join(WEB_ROOT, 'app/admin/notifications/page.tsx')), 'Notifications page must exist');

  // Verify RBAC client API methods
  const apiClientPath = path.join(WEB_ROOT, 'lib/api-client.ts');
  const clientContent = fs.readFileSync(apiClientPath, 'utf8');
  assert.ok(clientContent.includes('getPermissions:'), 'api client must have getPermissions');
  assert.ok(clientContent.includes('getRoles:'), 'api client must have getRoles');
  assert.ok(clientContent.includes('createRole:'), 'api client must have createRole');
  assert.ok(clientContent.includes('updateRolePermissions:'), 'api client must have updateRolePermissions');
});


