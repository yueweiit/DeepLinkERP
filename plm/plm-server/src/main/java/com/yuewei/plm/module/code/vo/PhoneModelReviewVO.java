package com.yuewei.plm.module.code.vo;

import java.util.List;

public record PhoneModelReviewVO(String key, List<String> codeValues, List<String> modelNames, long sourceCount) { }
