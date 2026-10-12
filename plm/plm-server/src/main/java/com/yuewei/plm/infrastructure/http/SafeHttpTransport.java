package com.yuewei.plm.infrastructure.http;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.net.*;
import java.net.http.*;
import java.nio.ByteBuffer;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.Flow;

/** Shared outbound transport policy. No credential URLs, redirects, system proxies or unbounded bodies. */
public final class SafeHttpTransport {
    private SafeHttpTransport() {}
    public static URI endpoint(String raw) {
        URI uri=URI.create(raw);
        boolean loopback=Set.of("127.0.0.1","localhost","::1","[::1]").contains(Objects.toString(uri.getHost(),""));
        if(uri.getHost()==null||uri.getUserInfo()!=null||uri.getRawQuery()!=null||uri.getFragment()!=null||!("https".equals(uri.getScheme())||loopback&&"http".equals(uri.getScheme())))throw new IllegalArgumentException("Endpoint must be HTTPS or loopback without credentials or query");
        return uri;
    }
    public static HttpClient client() {
        return HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).followRedirects(HttpClient.Redirect.NEVER)
            .proxy(new ProxySelector(){public List<Proxy> select(URI uri){return List.of(Proxy.NO_PROXY);}public void connectFailed(URI uri,SocketAddress address,IOException error){}}).build();
    }
    public static HttpResponse.BodyHandler<byte[]> boundedBody(int max) {
        return info->new LimitedSubscriber(info.headers().firstValueAsLong("Content-Length").orElse(-1)>max?0:max);
    }
    private static final class LimitedSubscriber implements HttpResponse.BodySubscriber<byte[]> {
        private final CompletableFuture<byte[]> result=new CompletableFuture<>();
        private final ByteArrayOutputStream bytes=new ByteArrayOutputStream();
        private final int max;private Flow.Subscription subscription;
        LimitedSubscriber(int max){this.max=max;}
        public CompletionStage<byte[]> getBody(){return result;}
        public void onSubscribe(Flow.Subscription subscription){this.subscription=subscription;subscription.request(1);}
        public void onNext(List<ByteBuffer> buffers){for(var buffer:buffers){if(bytes.size()+buffer.remaining()>max){subscription.cancel();result.completeExceptionally(new IllegalStateException("Response exceeds configured limit"));return;}byte[] part=new byte[buffer.remaining()];buffer.get(part);bytes.writeBytes(part);}subscription.request(1);}
        public void onError(Throwable error){result.completeExceptionally(error);}
        public void onComplete(){result.complete(bytes.toByteArray());}
    }
}
