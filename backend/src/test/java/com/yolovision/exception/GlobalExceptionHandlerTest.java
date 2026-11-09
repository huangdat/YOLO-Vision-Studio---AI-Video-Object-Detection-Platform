package com.yolovision.exception;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

class GlobalExceptionHandlerTest {

    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        mockMvc = MockMvcBuilders.standaloneSetup(new TestController())
                .setControllerAdvice(new GlobalExceptionHandler()).build();
    }

    @Test
    void unexpectedExceptionsDoNotLeakInternalDetails() throws Exception {
        mockMvc.perform(get("/test/failure"))
                .andExpect(status().isInternalServerError())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_PROBLEM_JSON))
                .andExpect(jsonPath("$.detail").value("An unexpected error occurred."))
                .andExpect(jsonPath("$.status").value(500))
                .andExpect(jsonPath("$.stackTrace").doesNotExist());
    }

    @Test
    void invalidRequestIncludesFieldErrors() throws Exception {
        mockMvc.perform(post("/test/validation").contentType(MediaType.APPLICATION_JSON).content("{\"name\":\"\"}"))
                .andExpect(status().isBadRequest())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_PROBLEM_JSON))
                .andExpect(jsonPath("$.detail").value("Request validation failed."))
                .andExpect(jsonPath("$.errors.name").isNotEmpty());
    }

    @Test
    void malformedJsonUsesProblemDetails() throws Exception {
        mockMvc.perform(post("/test/validation").contentType(MediaType.APPLICATION_JSON).content("{"))
                .andExpect(status().isBadRequest())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_PROBLEM_JSON))
                .andExpect(jsonPath("$.status").value(400));
    }

    @Test
    void anUnreachableDatabaseIsServiceUnavailableNotAnInternalError() throws Exception {
        // Seen live in Phase 10: with PostgreSQL stopped, opening the transaction fails with
        // CannotCreateTransactionException (not a DataAccessException).
        for (String path : new String[] {"/test/no-transaction", "/test/data-access"}) {
            mockMvc.perform(get(path))
                    .andExpect(status().isServiceUnavailable())
                    .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_PROBLEM_JSON))
                    .andExpect(jsonPath("$.code").value("SERVICE_UNAVAILABLE"))
                    .andExpect(jsonPath("$.detail").value("The data store is temporarily unavailable."));
        }
    }

    @RestController
    static class TestController {

        @GetMapping("/test/failure")
        public String fail() {
            throw new IllegalStateException("Sensitive implementation details");
        }

        @GetMapping("/test/no-transaction")
        public String noTransaction() {
            throw new org.springframework.transaction.CannotCreateTransactionException(
                    "Could not open JPA EntityManager for transaction");
        }

        @GetMapping("/test/data-access")
        public String dataAccess() {
            throw new org.springframework.dao.DataAccessResourceFailureException("Connection refused");
        }

        @PostMapping("/test/validation")
        public String validate(@Valid @RequestBody TestRequest request) {
            return request.name();
        }
    }

    record TestRequest(@NotBlank String name) {
    }
}
