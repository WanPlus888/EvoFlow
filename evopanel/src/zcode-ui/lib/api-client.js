/**
 * ZCode `@/` resolves to `src/zcode-ui`. Re-export AI Ops Brain's gateway client
 * so vendored UI (`@/lib/api-client.js`) and React wrappers share one implementation.
 */
export {
  apiUrl,
  apiUrlAsync,
  getGatewayBaseUrl,
  tasksAPI,
} from '../../lib/api-client.js'
