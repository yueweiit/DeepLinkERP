package com.yuewei.plm.module.bom.service;

import java.util.Optional;

public interface BomProcessRouteLookup {
    Optional<Route> findByCode(Long productId, String routeCode);

    record Route(Long processId, String routeCode, String routeName) {
    }
}
