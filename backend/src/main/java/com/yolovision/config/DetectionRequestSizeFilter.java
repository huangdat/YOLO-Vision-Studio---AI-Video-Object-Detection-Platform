package com.yolovision.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ReadListener;
import jakarta.servlet.ServletException;
import jakarta.servlet.ServletInputStream;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletRequestWrapper;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.time.Instant;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ProblemDetail;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * Bounds detection submission bodies before JSON parsing. A declared oversize body gets 413;
 * a body without Content-Length is cut off at the limit, which fails parsing with 400.
 */
@Component
public class DetectionRequestSizeFilter extends OncePerRequestFilter {

    static final String PATH = "/api/v1/detections";

    private final int maxBytes;
    private final ObjectMapper objectMapper;

    public DetectionRequestSizeFilter(DetectionApiProperties properties, ObjectMapper objectMapper) {
        this.maxBytes = properties.maxRequestBytes();
        this.objectMapper = objectMapper;
    }

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        return !("POST".equals(request.getMethod()) && PATH.equals(request.getRequestURI()));
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        long declared = request.getContentLengthLong();
        if (declared > maxBytes) {
            ProblemDetail problem = ProblemDetail.forStatusAndDetail(HttpStatus.PAYLOAD_TOO_LARGE,
                    "The request body exceeds " + maxBytes + " bytes.");
            problem.setProperty("code", "PAYLOAD_TOO_LARGE");
            problem.setProperty("timestamp", Instant.now().toString());
            response.setStatus(HttpStatus.PAYLOAD_TOO_LARGE.value());
            response.setContentType(MediaType.APPLICATION_PROBLEM_JSON_VALUE);
            objectMapper.writeValue(response.getOutputStream(), problem);
            return;
        }
        chain.doFilter(declared >= 0 ? request : new BoundedRequest(request, maxBytes), response);
    }

    private static final class BoundedRequest extends HttpServletRequestWrapper {
        private final int limit;

        private BoundedRequest(HttpServletRequest request, int limit) {
            super(request);
            this.limit = limit;
        }

        @Override
        public ServletInputStream getInputStream() throws IOException {
            ServletInputStream delegate = super.getInputStream();
            return new ServletInputStream() {
                private long read;

                @Override
                public int read() throws IOException {
                    int value = delegate.read();
                    if (value >= 0 && ++read > limit) {
                        throw new IOException("Request body exceeds the configured limit");
                    }
                    return value;
                }

                @Override
                public int read(byte[] buffer, int offset, int length) throws IOException {
                    int count = delegate.read(buffer, offset, length);
                    if (count > 0 && (read += count) > limit) {
                        throw new IOException("Request body exceeds the configured limit");
                    }
                    return count;
                }

                @Override
                public boolean isFinished() {
                    return delegate.isFinished();
                }

                @Override
                public boolean isReady() {
                    return delegate.isReady();
                }

                @Override
                public void setReadListener(ReadListener listener) {
                    delegate.setReadListener(listener);
                }
            };
        }
    }
}
