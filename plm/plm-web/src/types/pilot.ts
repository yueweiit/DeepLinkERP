export type PilotRole = 'administrator' | 'domestic' | 'finance' | 'supplier' | 'mexico'
export type PilotEntity = 'item' | 'mold' | 'product' | 'file'
export interface PilotScope { entityType: PilotEntity; entityId: number }
export interface PilotUser {
 userId: number; username: string; displayName: string; departmentName: string; status: 'active' | 'inactive'
 allPermissions: boolean; roleCode: PilotRole | null; allObjects: boolean | null; dingtalkUserId: string | null
 permissions: string[]; fieldGroups: string[]; scopes: PilotScope[]; version: number | null
}
export interface PilotRoleDefinition { roleCode: PilotRole; permissions: string[] }
export interface PilotUserInput {
 username: string; displayName: string; departmentName: string; roleCode: PilotRole; status: 'active' | 'inactive'
 allObjects: boolean; dingtalkUserId: string; permissions: string[]; fieldGroups: string[]; scopes: PilotScope[]; password: string; beforeVersion: number | null
}
export interface PilotTask { [key: string]: unknown; moldSetId: number; itemId: number; assetNumber: string; setName: string; styleName: string; compatibleModels: string; plannedMoldDeliveryDate: string | null }
export interface PilotFile { attachmentId: number; fileName: string; fileCategory: string; versionNo: string | null }
export const pilotRoleNames: Record<PilotRole,string> = { administrator: '管理员', domestic: '国内职责', finance: '财务', supplier: '供应商', mexico: '墨西哥' }
