package com.tricloud.app.api;

import java.util.List;
import java.util.Map;

public class Models {

    public static class Provider {
        public String id;
        public String name;
    }

    public static class CloudAccount {
        public int id;
        public String provider;
        public String name;
    }

    public static class Instance {
        public String id;
        public String name;
        public String status;
        public String public_ip;
        public String private_ip;
        public String region;
        public String shape;
        public Map<String, Object> extra;
    }

    public static class Billing {
        public double total;
        public String currency;
        public String period;
        public Double credit_used;
        public List<BillingService> services;
    }

    public static class BillingService {
        public String name;
        public double cost;
    }
}
