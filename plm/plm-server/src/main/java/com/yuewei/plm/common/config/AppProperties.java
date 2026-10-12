package com.yuewei.plm.common.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "app")
public class AppProperties {

    private final Security security = new Security();
    private final Storage storage = new Storage();
    private final PhoneWatch phoneWatch = new PhoneWatch();

    public Security getSecurity() {
        return security;
    }

    public Storage getStorage() {
        return storage;
    }

    public PhoneWatch getPhoneWatch() {
        return phoneWatch;
    }

    public static class Security {

        private boolean enabled = true;
        private String devToken = "dev-token";

        public boolean isEnabled() {
            return enabled;
        }

        public void setEnabled(boolean enabled) {
            this.enabled = enabled;
        }

        public String getDevToken() {
            return devToken;
        }

        public void setDevToken(String devToken) {
            this.devToken = devToken;
        }
    }

    public static class Storage {

        private String localRoot = "data/uploads";
        private long maxFileSizeBytes = 209_715_200L;
        private String allowedExtensions = "pdf,doc,docx,xls,xlsx,ppt,pptx,txt,csv,jpg,jpeg,png,webp,zip,rar,7z,dwg,dxf,step,stp,igs,iges,stl,obj,3dm,prt,sldprt,sldasm";

        public String getLocalRoot() {
            return localRoot;
        }

        public void setLocalRoot(String localRoot) {
            this.localRoot = localRoot;
        }

        public long getMaxFileSizeBytes() {
            return maxFileSizeBytes;
        }

        public void setMaxFileSizeBytes(long maxFileSizeBytes) {
            this.maxFileSizeBytes = maxFileSizeBytes;
        }

        public String getAllowedExtensions() {
            return allowedExtensions;
        }

        public void setAllowedExtensions(String allowedExtensions) {
            this.allowedExtensions = allowedExtensions;
        }
    }

    public static class PhoneWatch {
        private boolean enabled;
        private String baseUrl = "http://phone-watch:8000";
        private String token = "";
        private int connectTimeoutMs = 2_000;
        private int readTimeoutMs = 10_000;

        public boolean isEnabled() { return enabled; }
        public void setEnabled(boolean enabled) { this.enabled = enabled; }
        public String getBaseUrl() { return baseUrl; }
        public void setBaseUrl(String baseUrl) { this.baseUrl = baseUrl; }
        public String getToken() { return token; }
        public void setToken(String token) { this.token = token; }
        public int getConnectTimeoutMs() { return connectTimeoutMs; }
        public void setConnectTimeoutMs(int connectTimeoutMs) { this.connectTimeoutMs = connectTimeoutMs; }
        public int getReadTimeoutMs() { return readTimeoutMs; }
        public void setReadTimeoutMs(int readTimeoutMs) { this.readTimeoutMs = readTimeoutMs; }
    }
}
