package com.yuewei.plm.module.process.repository.typehandler;

import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;

import java.sql.PreparedStatement;
import java.sql.Types;
import org.junit.jupiter.api.Test;

class PostgresJsonbStringTypeHandlerTest {

    @Test
    void writesJsonAsPostgresOtherType() throws Exception {
        PreparedStatement statement = mock(PreparedStatement.class);
        PostgresJsonbStringTypeHandler handler = new PostgresJsonbStringTypeHandler();

        handler.setNonNullParameter(statement, 1, "{\"temperature\":80}", null);

        verify(statement).setObject(1, "{\"temperature\":80}", Types.OTHER);
    }
}
