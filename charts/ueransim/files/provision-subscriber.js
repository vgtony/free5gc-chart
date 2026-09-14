// Schema: free5gc/webconsole v1.2.0 (free5GC v3.3.0), backend/WebUI/api_webui.go.
// Run with mongosh --nodb. Credentials are read only from Secret-backed env vars.
const fs = require('fs');
const crypto = require('crypto');
const config = JSON.parse(fs.readFileSync(process.env.SUBSCRIBER_CONFIG || '/provision/subscriber.json', 'utf8'));
function requireThat(ok, message) { if (!ok) throw new Error(message); }
const key = process.env.UE_KEY || '';
const op = process.env.UE_OP || '';
requireThat(/^[a-fA-F0-9]{32}$/.test(key) && /^[a-fA-F0-9]{32}$/.test(op), 'Invalid UE credentials');
requireThat(/^imsi-[0-9]{15}$/.test(config.supi), 'Invalid SUPI');
requireThat(/^[0-9]{3}$/.test(config.mcc) && /^[0-9]{2,3}$/.test(config.mnc), 'Invalid PLMN');
requireThat(config.supi.startsWith('imsi-' + config.mcc + config.mnc), 'SUPI does not match MCC/MNC');
requireThat(['OP', 'OPC'].includes(config.opType), 'Invalid OP type');
requireThat(/^[a-fA-F0-9]{4}$/.test(config.amf), 'Invalid authentication management field');
requireThat(/^[a-fA-F0-9]{12}$/.test(config.initialSqn), 'Invalid initial sequence number');
requireThat(Number.isFinite(config.waitSeconds) && config.waitSeconds > 0, 'waitSeconds must be positive');
requireThat(Array.isArray(config.sessions) && config.sessions.length > 0, 'At least one UE session is required');
let opc = op.toLowerCase();
if (config.opType === 'OP') {
    const bytes = Buffer.from(op, 'hex');
    const cipher = crypto.createCipheriv('aes-128-ecb', Buffer.from(key, 'hex'), null);
    cipher.setAutoPadding(false);
    const encrypted = Buffer.concat([cipher.update(bytes), cipher.final()]);
    opc = Buffer.from(encrypted.map((value, i) => value ^ bytes[i])).toString('hex');
}
const ueFilter = {ueId: config.supi};
const plmnFilter = {...ueFilter, servingPlmnId: config.mcc + config.mnc};
const slices = new Map();
function sliceId(slice) {
    requireThat(slice && Number.isInteger(slice.sst) && slice.sst >= 0 && slice.sst <= 255, 'Invalid slice SST');
    requireThat(slice.sd === undefined || /^[a-fA-F0-9]{6}$/.test(slice.sd), 'Invalid slice SD');
    return slice.sst.toString(16).padStart(2, '0') + (slice.sd || '').toLowerCase();
}
function addSlice(slice) {
    const id = sliceId(slice);
    const normalized = {sst: slice.sst};
    if (slice.sd !== undefined) normalized.sd = slice.sd.toLowerCase();
    if (!slices.has(id)) slices.set(id, {slice: normalized, dnns: {}});
    return slices.get(id);
}
for (const slice of [...config.defaultNssai, ...config.configuredNssai]) addSlice(slice);
for (const session of config.sessions) {
    // This chart's data plane is IPv4. Fail rather than silently provision a different session type.
    requireThat(session.type === 'IPv4', 'Automatic provisioning currently supports IPv4 sessions only');
    requireThat(/^[a-zA-Z0-9][a-zA-Z0-9-]*$/.test(session.apn || ''), 'Automatic provisioning requires a simple DNN without dots');
    const entry = addSlice(session.slice);
    entry.dnns[session.apn] = {
        pduSessionTypes: {defaultSessionType: 'IPV4', allowedSessionTypes: ['IPV4']},
        sscModes: {defaultSscMode: 'SSC_MODE_1', allowedSscModes: ['SSC_MODE_1']},
        '5gQosProfile': {'5qi': 9, arp: {priorityLevel: 8}, priorityLevel: 8},
        sessionAmbr: config.sessionAmbr,
    };
}
const defaults = config.defaultNssai.length ? config.defaultNssai.map(s => addSlice(s).slice) : [addSlice(config.sessions[0].slice).slice];
const defaultIds = new Set(defaults.map(sliceId));
const authFields = {
    authenticationMethod: '5G_AKA', authenticationManagementField: config.amf,
    permanentKey: {permanentKeyValue: key.toLowerCase(), encryptionKey: 0, encryptionAlgorithm: 0},
    opc: {opcValue: opc, encryptionKey: 0, encryptionAlgorithm: 0},
};
const records = [{collection: 'subscriptionData.provisionedData.amData', filter: plmnFilter, fields: {
    nssai: {defaultSingleNssais: defaults, singleNssais: [...slices.entries()].filter(([id]) => !defaultIds.has(id)).map(([, e]) => e.slice)},
    subscribedUeAmbr: config.ueAmbr,
}}];
const selection = {}, policy = {};
for (const [id, entry] of slices) {
    if (!Object.keys(entry.dnns).length) continue;
    records.push({collection: 'subscriptionData.provisionedData.smData', filter: {...plmnFilter, singleNssai: entry.slice}, fields: {dnnConfigurations: entry.dnns}});
    selection[id] = {dnnInfos: Object.keys(entry.dnns).map(dnn => ({dnn}))};
    policy[id] = {snssai: entry.slice, smPolicyDnnData: Object.fromEntries(Object.keys(entry.dnns).map(dnn => [dnn, {dnn}]))};
}
records.push(
    {collection: 'subscriptionData.provisionedData.smfSelectionSubscriptionData', filter: plmnFilter, fields: {subscribedSnssaiInfos: selection}},
    {collection: 'policyData.ues.amData', filter: ueFilter, fields: {subscCats: ['free5gc']}},
    {collection: 'policyData.ues.smData', filter: ueFilter, fields: {smPolicySnssaiData: policy}},
);
// Connect with a bounded retry. Do not print URIs, credentials or raw database errors.
const deadline = Date.now() + config.waitSeconds * 1000;
let database;
while (!database) {
    try {
        const connection = new Mongo(process.env.MONGO_URI);
        const candidate = connection.getDB(config.database);
        requireThat(candidate.runCommand({ping: 1}).ok === 1, 'MongoDB ping failed');
        database = candidate;
    } catch (_) {
        if (Date.now() >= deadline) throw new Error('MongoDB unavailable; check service, credentials and network access');
        print('Waiting for MongoDB'); sleep(2000);
    }
}
const authCollection = database.getCollection('subscriptionData.authenticationData.authenticationSubscription');
const existing = authCollection.findOne(ueFilter);
if (existing) {
    // Do not silently rotate another installation's subscriber credentials.
    const sameKey = String((existing.permanentKey || {}).permanentKeyValue || '').toLowerCase() === key.toLowerCase();
    const sameOpc = String((existing.opc || {}).opcValue || '').toLowerCase() === opc;
    requireThat(sameKey && sameOpc && existing.authenticationManagementField === config.amf && existing.authenticationMethod === '5G_AKA',
        'Existing subscriber authentication differs; supply matching credentials or explicitly migrate the subscriber');
}
// Upsert only this subscriber. $setOnInsert preserves an SQN advanced by the core.
const initialSequence = config.sequenceNumberFormat === 'object'
    ? {sqn: config.initialSqn, sqnScheme: 'NON_TIME_BASED', ind: 0} : config.initialSqn;
requireThat(['string', 'object'].includes(config.sequenceNumberFormat), 'Invalid sequenceNumberFormat');
authCollection.updateOne(ueFilter, {$setOnInsert: {...ueFilter, ...authFields, sequenceNumber: initialSequence}}, {upsert: true});
for (const record of records) {
    database.getCollection(record.collection).updateOne(record.filter,
        {$set: record.fields, $setOnInsert: record.filter}, {upsert: true});
}
print('Subscriber provisioning completed');
