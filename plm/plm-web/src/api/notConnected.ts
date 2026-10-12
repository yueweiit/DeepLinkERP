export class FrontendFeatureNotConnectedError extends Error {
  constructor(featureName: string) {
    super(`${featureName}接口未接入，整体测试阶段不展示前端假数据`)
    this.name = 'FrontendFeatureNotConnectedError'
  }
}

export function notConnected<T>(featureName: string): Promise<T> {
  return Promise.reject(new FrontendFeatureNotConnectedError(featureName))
}
