import type { BackendApi, Service } from '../api/client';
export type Snapshot = {workspace_id: string; snapshot_id: string};
type Api = (service: Service, path: string, options: Parameters<BackendApi['request']>[2]) => Promise<unknown>;
type Dispose = () => void | Promise<unknown>;
type Options = {api: Api; sessionId: string; stageId: string; onReady: (snapshot: Snapshot) => void | Promise<void>};
export function mountRecording(root: HTMLElement, options: Options & {recordingConsentId: string; video: boolean}): Dispose;
export function mountBoard(root: HTMLElement, options: Options & {boardId?: string}): Promise<Dispose>;
export function mountProctoring(options: {api: Api; sessionId: string; stageId: string; onStatus?: (state:{status:string})=>void}): Promise<{flush:()=>Promise<boolean>;dispose:()=>Promise<boolean>}>;
