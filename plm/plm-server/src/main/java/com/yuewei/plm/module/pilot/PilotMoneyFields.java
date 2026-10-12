package com.yuewei.plm.module.pilot;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.Locale;
import java.util.Set;
import java.util.regex.Pattern;

/** One classification for request authorization and legacy response redaction. */
final class PilotMoneyFields {
 private static final Set<String> PUBLIC_MARKET_FIELDS=Set.of("phoneprice","pricecurrency");
 private static final Pattern INTERNAL_MONEY=Pattern.compile(".*(?:cost|price|amount|budget|expense|quotation|currency|tax).*");
 private static final String[] PATCH_VALUES={"before","after","value"};
 private PilotMoneyFields(){}
 static boolean isProtected(String name){String key=name.toLowerCase(Locale.ROOT);return !PUBLIC_MARKET_FIELDS.contains(key)&&INTERNAL_MONEY.matcher(key).matches();}
 static boolean containsProtectedValue(JsonNode node){
  if(node.isObject()){
   // Shared cell-patch DTOs name the edited field as a value, not as a JSON key.
   JsonNode field=node.get("field");
   if(field!=null&&field.isTextual()&&isProtected(field.asText()))
    for(String valueKey:PATCH_VALUES){JsonNode value=node.get(valueKey);if(value!=null&&!value.isNull())return true;}
   var fields=node.fields();while(fields.hasNext()){var fieldValue=fields.next();if((isProtected(fieldValue.getKey())&&!fieldValue.getValue().isNull())||containsProtectedValue(fieldValue.getValue()))return true;}
  }else if(node.isArray()){for(JsonNode value:node)if(containsProtectedValue(value))return true;}
  return false;
 }
}
