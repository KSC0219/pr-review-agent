"""Seeded-defect evaluation set.

Each case is a small pull request against a Spring Boot codebase. Lines start
with "+" (added), "-" (removed) or " " (context). `expect` lists the defects
planted in the PR as (category, marker), where marker is a substring of the
added line that a correct review should point at. Clean cases expect nothing,
so any comment on them is a false positive.
"""

from __future__ import annotations

from pathlib import Path

MAIN = "src/main/java/com/example/"
TEST = "src/test/java/com/example/"

CASES: list[dict] = [
    # ---------------------------------------------------------------- bugs
    dict(id="bug01_string_eq", path=MAIN + "order/OrderService.java", start=40, body=[
        "     public boolean isCancellable(Order order) {",
        "-        return order.getStatus().equals(\"NEW\");",
        "+        String status = order.getStatus();",
        "+        return status == \"NEW\" || status == \"PENDING\";",
        "     }",
    ], expect=[("bug", "status ==")]),
    dict(id="bug02_optional_get", path=MAIN + "user/UserService.java", start=22, body=[
        "     public UserDto findByEmail(String email) {",
        "-        return repo.findByEmail(email).map(mapper::toDto).orElseThrow(UserNotFoundException::new);",
        "+        User user = repo.findByEmail(email).get();",
        "+        return mapper.toDto(user);",
        "     }",
    ], expect=[("bug", ".get()")]),
    dict(id="bug03_off_by_one", path=MAIN + "report/ReportBuilder.java", start=31, body=[
        "     public long total(List<Invoice> invoices) {",
        "         long sum = 0;",
        "-        for (Invoice invoice : invoices) {",
        "-            sum += invoice.getAmount();",
        "+        for (int i = 0; i <= invoices.size(); i++) {",
        "+            sum += invoices.get(i).getAmount();",
        "         }",
        "         return sum;",
    ], expect=[("bug", "i <= invoices.size()")]),
    dict(id="bug04_resource_leak", path=MAIN + "export/CsvExporter.java", start=18, body=[
        "     public void export(List<String> rows, Path target) throws IOException {",
        "-        try (BufferedWriter writer = Files.newBufferedWriter(target)) {",
        "-            for (String row : rows) { writer.write(row); writer.newLine(); }",
        "-        }",
        "+        BufferedWriter writer = Files.newBufferedWriter(target);",
        "+        for (String row : rows) {",
        "+            writer.write(row);",
        "+            writer.newLine();",
        "+        }",
        "     }",
    ], expect=[("bug", "BufferedWriter writer = Files.newBufferedWriter")]),
    dict(id="bug05_swallowed_exception", path=MAIN + "payment/PaymentService.java", start=55, body=[
        "     public void capture(String paymentId) {",
        "-        gateway.capture(paymentId);",
        "+        try {",
        "+            gateway.capture(paymentId);",
        "+        } catch (Exception e) { }",
        "         repo.markCaptured(paymentId);",
        "     }",
    ], expect=[("bug", "catch (Exception e)")]),
    dict(id="bug06_integer_division", path=MAIN + "stats/StatsService.java", start=12, body=[
        "     public double successRate(int success, int total) {",
        "-        return total == 0 ? 0 : (success * 100.0) / total;",
        "+        return (success / total) * 100;",
        "     }",
    ], expect=[("bug", "(success / total) * 100")]),
    dict(id="bug07_null_map_value", path=MAIN + "pricing/DiscountService.java", start=27, body=[
        "     public BigDecimal apply(String code, BigDecimal price) {",
        "-        BigDecimal rate = rates.getOrDefault(code, BigDecimal.ZERO);",
        "+        BigDecimal rate = rates.get(code);",
        "+        return price.subtract(price.multiply(rate));",
        "-        return price.subtract(price.multiply(rate));",
        "     }",
    ], expect=[("bug", "price.multiply(rate)")]),
    dict(id="bug08_concurrent_modification", path=MAIN + "cart/CartService.java", start=44, body=[
        "     public void removeExpired(Cart cart) {",
        "-        cart.getItems().removeIf(CartItem::isExpired);",
        "+        for (CartItem item : cart.getItems()) {",
        "+            if (item.isExpired()) {",
        "+                cart.getItems().remove(item);",
        "+            }",
        "+        }",
        "     }",
    ], expect=[("bug", "cart.getItems().remove(item)")]),
    # ------------------------------------------------------------ security
    dict(id="sec01_sql_injection", path=MAIN + "user/UserDao.java", start=19, body=[
        "     public List<User> search(String name) {",
        "-        return jdbc.query(\"SELECT * FROM users WHERE name = ?\", mapper, name);",
        "+        String sql = \"SELECT * FROM users WHERE name = '\" + name + \"'\";",
        "+        return jdbc.query(sql, mapper);",
        "     }",
    ], expect=[("security", "SELECT * FROM users")]),
    dict(id="sec02_hardcoded_secret", path=MAIN + "config/JwtConfig.java", start=9, body=[
        " public class JwtConfig {",
        "-    @Value(\"${jwt.secret}\")",
        "-    private String secret;",
        "+    private String jwtSecret = \"s3cr3t-signing-key-2024\";",
        " ",
    ], expect=[("security", "jwtSecret =")]),
    dict(id="sec03_password_in_log", path=MAIN + "auth/LoginController.java", start=30, body=[
        "     public ResponseEntity<TokenDto> login(@RequestBody LoginRequest request) {",
        "+        log.info(\"Login attempt user={} password={}\", request.getUsername(), request.getPassword());",
        "         return ResponseEntity.ok(authService.login(request));",
        "     }",
    ], expect=[("security", "log.info")]),
    dict(id="sec04_md5_password", path=MAIN + "auth/PasswordHasher.java", start=11, body=[
        "     public String hash(String password) throws NoSuchAlgorithmException {",
        "-        return encoder.encode(password);",
        "+        MessageDigest digest = MessageDigest.getInstance(\"MD5\");",
        "+        return HexFormat.of().formatHex(digest.digest(password.getBytes()));",
        "     }",
    ], expect=[("security", "MessageDigest.getInstance")]),
    dict(id="sec05_path_traversal", path=MAIN + "files/DownloadController.java", start=24, body=[
        "     @GetMapping(\"/files\")",
        "     public Resource download(@RequestParam String name) {",
        "+        File file = new File(\"/var/app/uploads/\" + name);",
        "+        return new FileSystemResource(file);",
        "-        return storage.load(name);",
        "     }",
    ], expect=[("security", "new File(")]),
    dict(id="sec06_missing_authorization", path=MAIN + "admin/AdminController.java", start=16, body=[
        "-    @PreAuthorize(\"hasRole('ADMIN')\")",
        "     @DeleteMapping(\"/admin/users/{id}\")",
        "+    @PermitAll",
        "     public void deleteUser(@PathVariable Long id) {",
        "         userService.delete(id);",
    ], expect=[("security", "@PermitAll")]),
    dict(id="sec07_command_injection", path=MAIN + "tools/PingService.java", start=13, body=[
        "     public String ping(String host) throws IOException {",
        "+        Process process = Runtime.getRuntime().exec(\"ping -c 1 \" + host);",
        "+        return new String(process.getInputStream().readAllBytes());",
        "-        return InetAddress.getByName(host).isReachable(1000) ? \"up\" : \"down\";",
        "     }",
    ], expect=[("security", "Runtime.getRuntime().exec")]),
    dict(id="sec08_insecure_random_token", path=MAIN + "auth/ResetTokenService.java", start=20, body=[
        "     public String newResetToken() {",
        "-        byte[] bytes = new byte[32];",
        "-        secureRandom.nextBytes(bytes);",
        "-        return Base64.getUrlEncoder().encodeToString(bytes);",
        "+        return String.valueOf(new Random().nextInt(999999));",
        "     }",
    ], expect=[("security", "new Random()")]),
    # --------------------------------------------------------- missing tests
    dict(id="tst01_new_refund_method", path=MAIN + "payment/RefundService.java", start=38, body=[
        "     }",
        " ",
        "+    public Refund refund(String paymentId, BigDecimal amount) {",
        "+        Payment payment = repo.findById(paymentId).orElseThrow(PaymentNotFoundException::new);",
        "+        if (amount.compareTo(payment.getAmount()) > 0) {",
        "+            throw new IllegalArgumentException(\"refund exceeds payment\");",
        "+        }",
        "+        return gateway.refund(paymentId, amount);",
        "+    }",
        " }",
    ], expect=[("tests", "public Refund refund")]),
    dict(id="tst02_new_status_transition", path=MAIN + "fault/FaultService.java", start=61, body=[
        "     }",
        " ",
        "+    public Fault reopen(Long id) {",
        "+        Fault fault = repo.findById(id).orElseThrow(FaultNotFoundException::new);",
        "+        if (fault.getStatus() != FaultStatus.RESOLVED) {",
        "+            throw new InvalidTransitionException(fault.getStatus(), FaultStatus.OPEN);",
        "+        }",
        "+        fault.setStatus(FaultStatus.OPEN);",
        "+        return repo.save(fault);",
        "+    }",
        " }",
    ], expect=[("tests", "public Fault reopen")]),
    dict(id="tst03_new_endpoint", path=MAIN + "order/OrderController.java", start=47, body=[
        "     }",
        " ",
        "+    @PostMapping(\"/orders/{id}/cancel\")",
        "+    public ResponseEntity<OrderDto> cancel(@PathVariable Long id) {",
        "+        return ResponseEntity.ok(orderService.cancel(id));",
        "+    }",
        " }",
    ], expect=[("tests", "public ResponseEntity<OrderDto> cancel")]),
    dict(id="tst04_new_validation_branch", path=MAIN + "user/SignupService.java", start=25, body=[
        "     }",
        " ",
        "+    public boolean isStrongPassword(String password) {",
        "+        if (password == null || password.length() < 12) {",
        "+            return false;",
        "+        }",
        "+        return password.chars().anyMatch(Character::isDigit)",
        "+                && password.chars().anyMatch(Character::isUpperCase);",
        "+    }",
        " }",
    ], expect=[("tests", "public boolean isStrongPassword")]),
    # ---------------------------------------------------------------- clean
    dict(id="ok01_rename_variable", path=MAIN + "order/OrderMapper.java", start=14, body=[
        "     public OrderDto toDto(Order order) {",
        "-        OrderDto d = new OrderDto();",
        "-        d.setId(order.getId());",
        "-        return d;",
        "+        OrderDto dto = new OrderDto();",
        "+        dto.setId(order.getId());",
        "+        return dto;",
        "     }",
    ], expect=[]),
    dict(id="ok02_parameterized_query", path=MAIN + "user/UserDao.java", start=33, body=[
        "     public Optional<User> findByEmail(String email) {",
        "+        List<User> users = jdbc.query(\"SELECT * FROM users WHERE email = ?\", mapper, email);",
        "+        return users.stream().findFirst();",
        "-        return Optional.empty();",
        "     }",
    ], expect=[]),
    dict(id="ok03_add_logging", path=MAIN + "fault/FaultService.java", start=29, body=[
        "     public Fault resolve(Long id) {",
        "+        log.info(\"Resolving fault id={}\", id);",
        "         Fault fault = repo.findById(id).orElseThrow(FaultNotFoundException::new);",
    ], expect=[]),
    dict(id="ok04_extract_constant", path=MAIN + "cart/CartService.java", start=10, body=[
        " public class CartService {",
        "+    private static final int MAX_ITEMS = 50;",
        " ",
        "     public void add(Cart cart, CartItem item) {",
        "-        if (cart.getItems().size() >= 50) {",
        "+        if (cart.getItems().size() >= MAX_ITEMS) {",
        "             throw new CartFullException();",
    ], expect=[]),
    dict(id="ok05_javadoc_only", path=MAIN + "pricing/DiscountService.java", start=20, body=[
        " ",
        "+    /**",
        "+     * Applies the discount for the given code. Unknown codes leave the price unchanged.",
        "+     */",
        "     public BigDecimal apply(String code, BigDecimal price) {",
    ], expect=[]),
    dict(id="ok06_test_only_change", path=TEST + "stats/StatsServiceTest.java", start=18, body=[
        "     }",
        " ",
        "+    @Test",
        "+    void successRateIsZeroWhenTotalIsZero() {",
        "+        assertEquals(0.0, service.successRate(0, 0));",
        "+    }",
        " }",
    ], expect=[]),
]


def build_diff(case: dict) -> str:
    old = sum(1 for line in case["body"] if line[0] in " -")
    new = sum(1 for line in case["body"] if line[0] in " +")
    head = [
        f"diff --git a/{case['path']} b/{case['path']}",
        f"--- a/{case['path']}",
        f"+++ b/{case['path']}",
        f"@@ -{case['start']},{old} +{case['start']},{new} @@",
    ]
    return "\n".join(head + case["body"]) + "\n"


def expected_lines(case: dict) -> list[dict]:
    """Resolve each marker to the new-file line number of the added line containing it."""
    resolved = []
    for category, marker in case["expect"]:
        line_no = case["start"]
        found = None
        for line in case["body"]:
            if line[0] == "-":
                continue
            if line[0] == "+" and marker in line and found is None:
                found = line_no
            line_no += 1
        if found is None:
            raise ValueError(f"{case['id']}: marker {marker!r} not found on an added line")
        resolved.append({"file": case["path"], "line": found, "category": category})
    return resolved


def write_cases(directory: str | Path) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for case in CASES:
        (directory / f"{case['id']}.diff").write_text(build_diff(case), encoding="utf-8")
    return directory
