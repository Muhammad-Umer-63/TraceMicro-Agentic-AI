package org.example;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.github.javaparser.JavaParser;
import com.github.javaparser.ParseResult;
import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.NodeList;
import com.github.javaparser.ast.body.*;
import com.github.javaparser.ast.expr.*;
import com.github.javaparser.ast.stmt.ExpressionStmt;
import com.github.javaparser.ast.stmt.ReturnStmt;
import com.github.javaparser.ast.stmt.Statement;
import com.github.javaparser.ast.type.ClassOrInterfaceType;
import com.github.javaparser.ast.type.Type;
import com.github.javaparser.ast.visitor.VoidVisitorAdapter;

import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.*;
import java.util.stream.Collectors;

/**
 * Analyzes Java source code to extract class relationships
 */
public class ClassRelationshipAnalyzer {
    private final List<String> projectPaths;
    private final Graph graph = new Graph();
    private final Map<String, Set<String>> importsByClass = new HashMap<>();
    private final Set<String> userDefinedClasses = new HashSet<>();
    
    // Static map to track code statements for all relationships
    private static final Map<String, Set<String>> relationshipStatements = new HashMap<>();
    
    
    // List of directories to exclude from analysis
    private static final List<String> EXCLUDED_DIRECTORIES = Arrays.asList(
        "tmp"
    );
    
    /**
     * Constructor that takes a single project path
     */
    public ClassRelationshipAnalyzer(String projectPath) {
        this.projectPaths = Collections.singletonList(projectPath);
    }
    
    /**
     * Constructor that takes multiple project paths
     */
    public ClassRelationshipAnalyzer(List<String> projectPaths) {
        this.projectPaths = new ArrayList<>(projectPaths);
    }
    
    /**
     * Get the graph of class relationships
     */
    public Graph getGraph() {
        return graph;
    }
    
    /**
     * Analyze the project and extract class relationships
     * Restructured to build complete class hierarchy before analyzing method calls
     */
    public void analyze() {
        try {
            // First phase: collect all user-defined classes from all project paths
            System.out.println("Collecting user-defined classes...");
            for (String projectPath : projectPaths) {
                Files.walk(Paths.get(projectPath))
                    .filter(path -> path.toString().endsWith(".java"))
                    .filter(this::shouldIncludePath)
                    .forEach(this::collectUserDefinedClasses);
            }
            
            System.out.println("Found " + userDefinedClasses.size() + " user-defined classes");
                
            // Second phase: build class hierarchy structure (inheritance relationships and method info)
            System.out.println("Building class hierarchy and collecting method information...");
            List<Path> allJavaFiles = new ArrayList<>();
            
            // First collect all Java files
            for (String projectPath : projectPaths) {
                Files.walk(Paths.get(projectPath))
                    .filter(path -> path.toString().endsWith(".java"))
                    .filter(this::shouldIncludePath)
                    .forEach(allJavaFiles::add);
            }
            
            // Then process them to build the class hierarchy
            for (Path file : allJavaFiles) {
                buildClassHierarchy(file);
            }
            
            // Process imports to resolve full class names
            System.out.println("Resolving imports...");
            resolveImports();
            
            // Third phase: analyze method calls and other relationships
            System.out.println("Analyzing class relationships and method calls...");
            for (Path file : allJavaFiles) {
                analyzeRelationships(file);
            }
            
            // Analyze repository classes to identify PERSISTS relationships with entities
            analyzeRepositoryRelationships();
            
            // Remove relationships to non-user-defined classes
            filterNonUserDefinedClasses();
            
        } catch (IOException e) {
            System.err.println("Error analyzing project: " + e.getMessage());
            e.printStackTrace();
        }
    }
    
    /**
     * Check if a path should be included in the analysis
     */
    private boolean shouldIncludePath(Path path) {
        String pathStr = path.toString();
        for (String excludedDir : EXCLUDED_DIRECTORIES) {
            if (pathStr.contains(excludedDir)) {
                return false;
            }
        }
        return true;
    }
    
    /**
     * Collect all user-defined classes from a file
     */
    private void collectUserDefinedClasses(Path file) {
        try {
            ParseResult<CompilationUnit> parseResult = new JavaParser().parse(file);
            if (parseResult.isSuccessful() && parseResult.getResult().isPresent()) {
                CompilationUnit cu = parseResult.getResult().get();
                
                // Extract package name
                String packageName = cu.getPackageDeclaration()
                    .map(pd -> pd.getNameAsString() + ".")
                    .orElse("");
                
                // Add each type (class/interface/enum) in the file
                cu.findAll(TypeDeclaration.class).forEach(type -> {
                    // Skip inner classes in this phase - we'll handle them with their outer class
                    if (!type.isNestedType()) {
                        String className = packageName + type.getNameAsString();
                        userDefinedClasses.add(className);
                    }
                });
            }
        } catch (IOException e) {
            System.err.println("Error collecting classes from file " + file + ": " + e.getMessage());
        }
    }
    
    /**
     * Build the class hierarchy structure (inheritance relationships only)
     */
    private void buildClassHierarchy(Path file) {
        try {
            ParseResult<CompilationUnit> parseResult = new JavaParser().parse(file);
            if (parseResult.isSuccessful() && parseResult.getResult().isPresent()) {
                CompilationUnit cu = parseResult.getResult().get();
                
                // Extract package name
                String packageName = cu.getPackageDeclaration()
                    .map(pd -> pd.getNameAsString() + ".")
                    .orElse("");
                
                // Store imports for later resolution
                Set<String> imports = cu.getImports().stream()
                    .map(i -> i.getNameAsString())
                    .collect(Collectors.toSet());
                
                // Process each type (class/interface/enum) in the file
                cu.findAll(TypeDeclaration.class).forEach(type -> {
                    // Skip inner classes in separate processing
                    if (type.isNestedType()) {
                        return;
                    }
                    
                    String className = packageName + type.getNameAsString();
                    
                    // Store imports for this class
                    importsByClass.put(className, imports);
                    
                    // Add this class as a node
                    addNodeIfUserDefined(className);
                    
                    // Collect method information for this class
                    collectMethodInfo(className, type);
                    
                    // Process inheritance relationships only
                    if (type instanceof ClassOrInterfaceDeclaration) {
                        ClassOrInterfaceDeclaration cls = (ClassOrInterfaceDeclaration) type;
                        
                        // Process extends relationships
                        for (ClassOrInterfaceType extendedType : cls.getExtendedTypes()) {
                            String targetClass = extendedType.getNameAsString();
                            String resolvedTarget = resolveClassName(targetClass);
                            
                            if (resolvedTarget != null && isUserDefinedClass(resolvedTarget)) {
                                graph.addRelationship(className, resolvedTarget, RelationshipType.EXTENDS);
                                
                                // Store the relationship statement
                                String fullKey = className + ":" + RelationshipType.EXTENDS.toString() + ":" + resolvedTarget;
                                relationshipStatements.computeIfAbsent(fullKey, k -> new LinkedHashSet<>())
                                    .add(cls.getNameAsString() + " extends " + extendedType.getNameAsString());
                            }
                        }
                        
                        // Process implements relationships
                        for (ClassOrInterfaceType implementedType : cls.getImplementedTypes()) {
                            String targetClass = implementedType.getNameAsString();
                            String resolvedTarget = resolveClassName(targetClass);
                            
                            if (resolvedTarget != null && isUserDefinedClass(resolvedTarget)) {
                                graph.addRelationship(className, resolvedTarget, RelationshipType.IMPLEMENTS);
                                
                                // Store the relationship statement
                                String fullKey = className + ":" + RelationshipType.IMPLEMENTS.toString() + ":" + resolvedTarget;
                                relationshipStatements.computeIfAbsent(fullKey, k -> new LinkedHashSet<>())
                                    .add(cls.getNameAsString() + " implements " + implementedType.getNameAsString());
                            }
                        }
                    }
                });
            }
        } catch (IOException e) {
            System.err.println("Error building class hierarchy from file " + file + ": " + e.getMessage());
        }
    }

    private void addNodeIfUserDefined(String className) {
        if (isUserDefinedClass(className)) {
            graph.addNode(className);
        }
    }
    
    /**
     * Collect method information for a class
     */
    private void collectMethodInfo(String className, TypeDeclaration<?> type) {
        // Get or create class details
        ClassDetails classDetails = graph.getClassDetail(className);
        if (classDetails == null) {
            return;
        }
        
        // Store class annotations
        NodeList<AnnotationExpr> annotations = type.getAnnotations();
        for (AnnotationExpr annotation : annotations) {
            classDetails.addAnnotation(annotation.toString());
        }
        
        // Process methods
        type.findAll(MethodDeclaration.class).forEach(method -> {
            // Create method info object
            String methodName = method.getNameAsString();
            String returnType = resolveClassName(method.getType().asString());
            MethodInfo methodInfo = new MethodInfo(methodName, returnType);
            
            // Set method modifiers
            methodInfo.setPublic(method.isPublic());
            methodInfo.setPrivate(method.isPrivate());
            methodInfo.setProtected(method.isProtected());
            methodInfo.setStatic(method.isStatic());
            methodInfo.setAbstract(method.isAbstract());
            methodInfo.setFinal(method.isFinal());
            
            // Add parameter types
            method.getParameters().forEach(param -> {
                String paramType = resolveClassName(param.getType().asString());
                methodInfo.addParameterType(paramType);
            });
            
            // Add method annotations
            for (AnnotationExpr annotation : method.getAnnotations()) {
                methodInfo.addAnnotation(annotation.toString());
            }
            
            // Add method to class details
            classDetails.addMethod(methodInfo);
        });
        
        // Process constructors
        type.findAll(ConstructorDeclaration.class).forEach(constructor -> {
            // Create method info object for the constructor
            String methodName = constructor.getNameAsString();
            MethodInfo methodInfo = new MethodInfo(methodName, className); // Constructor returns the class type
            
            // Set method modifiers
            methodInfo.setPublic(constructor.isPublic());
            methodInfo.setPrivate(constructor.isPrivate());
            methodInfo.setProtected(constructor.isProtected());
            methodInfo.setFinal(constructor.isFinal());
            
            // Add parameter types
            constructor.getParameters().forEach(param -> {
                String paramType = resolveClassName(param.getType().asString());
                methodInfo.addParameterType(paramType);
            });
            
            // Add method annotations
            for (AnnotationExpr annotation : constructor.getAnnotations()) {
                methodInfo.addAnnotation(annotation.toString());
            }
            
            // Add constructor to class details
            classDetails.addMethod(methodInfo);
        });
    }
    
    /**
     * Analyze relationships other than inheritance (method calls, field access, etc.)
     */
    private void analyzeRelationships(Path file) {
        try {
            ParseResult<CompilationUnit> parseResult = new JavaParser().parse(file);
            if (parseResult.isSuccessful() && parseResult.getResult().isPresent()) {
                CompilationUnit cu = parseResult.getResult().get();
                
                // Extract package name
                String packageName = cu.getPackageDeclaration()
                    .map(pd -> pd.getNameAsString() + ".")
                    .orElse("");
                
                // Process each type (class/interface/enum) in the file
                cu.findAll(TypeDeclaration.class).forEach(type -> {
                    // Skip inner classes in separate processing
                    if (type.isNestedType()) {
                        return;
                    }
                    
                    String className = packageName + type.getNameAsString();
                    ClassDetails classDetails = graph.getClassDetail(className);
                    
                    // Skip if class details not found
                    if (classDetails == null) {
                        return;
                    }
                    
                    // Create visitor to analyze relationships (excluding inheritance)
                    RelationshipVisitor visitor = new RelationshipVisitor(className, packageName);
                    type.accept(visitor, null);
                    
                    // Collect inner classes for this class
                    List innerClasses = type.findAll(TypeDeclaration.class).stream()
                        .filter(innerType -> innerType != type) // Skip the outer class itself
                        .collect(Collectors.toList());
                    
                    // If there are inner classes, add them to the class details
                    if (!innerClasses.isEmpty()) {
                        for (Object obj : innerClasses) {
                            TypeDeclaration<?> innerClass = (TypeDeclaration<?>) obj;
                            String innerClassName = innerClass.getNameAsString();
                            classDetails.addInnerClass(innerClassName);
                            
                            // Add inner class annotations
                            for (AnnotationExpr annotation : innerClass.getAnnotations()) {
                                classDetails.addInnerClassAnnotation(innerClassName, annotation.toString());
                            }
                        }
                    }
                });
            }
        } catch (IOException e) {
            System.err.println("Error analyzing relationships in file " + file + ": " + e.getMessage());
        }
    }
    
    /**
     * Check if a class is a user-defined class (not from excluded packages)
     */
    private boolean isUserDefinedClass(String className) {
        if (userDefinedClasses.contains(className)) {
            return true;
        }
        return false;
    }
    
    /**
     * Filter out relationships to non-user-defined classes
     */
    private void filterNonUserDefinedClasses() {
        Set<String> classesToRemove = new HashSet<>();
        Map<String, String> simpleToFullNameMap = new HashMap<>();
        
        // First pass: identify simple class names that have fully qualified counterparts
        for (String className : graph.getNodes().keySet()) {
            // Skip if already marked for removal
            if (classesToRemove.contains(className)) {
                continue;
            }
            
            // If this is an inner class, mark for removal (we'll handle it with its outer class)
            if (className.contains("$")) {
                classesToRemove.add(className);
                continue;
            }
            
            // Special handling for Java built-in types regardless of package structure
            if (className.equals("String") || className.equals("Integer") || className.equals("Boolean") || 
                className.equals("Long") || className.equals("Double") || className.equals("Object") ||
                className.equals("Exception") || className.equals("RuntimeException") || 
                className.equals("Class") || className.equals("ClassLoader") || 
                className.equals("IllegalArgumentException") || className.equals("StringBuilder") ||
                className.equals("Error") || className.equals("Throwable") || 
                className.equals("Thread") || className.equals("Runnable") ||
                className.contains("[]")) { // Also filter out array types
                classesToRemove.add(className);
                continue;
            }
            
            // Check if it's from excluded packages
            if (!isUserDefinedClass(className)) {
                classesToRemove.add(className);
                continue;
            }
            
            // Handle simple class names vs fully qualified names
            if (!className.contains(".")) {
                // This is a simple class name
                String simpleName = className;
                
                // Look for a fully qualified version of this class
                for (String fullClassName : graph.getNodes().keySet()) {
                    if (fullClassName.contains(".") && fullClassName.endsWith("." + simpleName)) {
                        // Found a fully qualified version - map simple name to full name
                        simpleToFullNameMap.put(simpleName, fullClassName);
                        classesToRemove.add(simpleName); // Remove the simple name version
                        break;
                    }
                }
            }
        }
        
        // Second pass: merge relationships from simple names to their fully qualified counterparts
        for (Map.Entry<String, String> entry : simpleToFullNameMap.entrySet()) {
            String simpleName = entry.getKey();
            String fullName = entry.getValue();
            
            // Get nodes for both versions
            ClassNode simpleNode = graph.getNodes().get(simpleName);
            ClassNode fullNode = graph.getNodes().get(fullName);
            
            if (simpleNode != null && fullNode != null) {
                // Copy relationships from simple name to full name
                for (Relationship rel : simpleNode.getRelationships()) {
                    String targetClass = rel.getTargetClass();
                    
                    // If target is also a simple name with a full name mapping, use the full name
                    if (simpleToFullNameMap.containsKey(targetClass)) {
                        targetClass = simpleToFullNameMap.get(targetClass);
                    }
                    
                    // Add relationship to the fully qualified node
                    fullNode.addRelationship(targetClass, rel.getType());
                }
            }
        }
        
        // Remove non-user classes from the graph
        for (String className : classesToRemove) {
            graph.removeNode(className);
        }
        
        // Final pass: filter relationships to non-user classes or classes not in the graph
        for (ClassNode node : graph.getNodes().values()) {
            List<Relationship> relationships = node.getRelationships();
            List<Relationship> filteredRelationships = new ArrayList<>();
            
            for (Relationship rel : relationships) {
                String targetClass = rel.getTargetClass();
                
                // Skip inner class relationships
                if (targetClass.contains("$")) {
                    continue;
                }
                
                // Skip relationships to framework classes or Java built-in classes
                if (!isUserDefinedClass(targetClass)) {
                    continue;
                }
                
                // Only keep relationships between user-defined classes that are still in the graph
                if (graph.getNodes().containsKey(targetClass)) {
                    filteredRelationships.add(rel);
                }
            }
            
            node.setRelationships(filteredRelationships);
        }
        
        System.out.println("Removed " + classesToRemove.size() + " classes (built-in classes, framework classes, and inner classes) from the analysis");
    }
    
    /**
     * Analyze repository classes to identify PERSISTS relationships with entities
     * Must be called after imports are resolved and before filtering non-user classes
     */
    private void analyzeRepositoryRelationships() {
        System.out.println("Analyzing repository relationships with entities...");
        
        // For each class, check if it's a repository and find its entity
        for (String className : graph.getNodes().keySet()) {
            ClassDetails classDetails = graph.getClassDetail(className);
            if (classDetails == null) {
                continue;
            }
            
            String role = classDetails.getMetadata("role");
            boolean isRepository = "Repository".equals(role);
            
            if (!isRepository) {
                // Also check annotations and class name
                if (className.contains("Repository") || className.contains("Dao") || className.contains("Mapper")) {
                    isRepository = true;
                    classDetails.addMetadata("role", "Repository");
                } else {
                    for (String annotation : classDetails.getAnnotations()) {
                        if (annotation.contains("Repository") || annotation.contains("Mapper")) {
                            isRepository = true;
                            classDetails.addMetadata("role", "Repository");
                            break;
                        }
                    }
                }
            }
            
            if (!isRepository) {
                continue;
            }
            
            // This is a repository class, find its entity
            Set<String> entitiesFound = findRepositoryEntities(className, classDetails);
            
            // Add PERSISTS relationships to all found entities
            for (String entityClassName : entitiesFound) {
                if (isUserDefinedClass(entityClassName) && graph.getNodes().containsKey(entityClassName)) {
                    // Add PERSISTS relationship
                    graph.addRelationship(className, entityClassName, RelationshipType.PERSISTS);
                    
                    // Add the code statement for this relationship
                    String fullKey = className + ":" + RelationshipType.PERSISTS.toString() + ":" + entityClassName;
                    relationshipStatements.computeIfAbsent(fullKey, k -> new LinkedHashSet<>())
                        .add(className + " persists " + entityClassName);
                }
            }
        }
    }
    
    /**
     * Find the entities that a repository persists by analyzing generic type parameters
     * in extended repository interfaces
     */
    private Set<String> findRepositoryEntities(String repoClassName, ClassDetails repoDetails) {
        Set<String> result = new HashSet<>();
        
        // Look for generic types in extended interfaces (JpaRepository, CrudRepository, etc.)
        ClassNode node = graph.getNodes().get(repoClassName);
        if (node != null) {
            // Track if we found a standard repository interface
            boolean isStandardRepositoryInterface = false;
            
            // Look for extends/implements relationships
            for (Relationship rel : node.getRelationships()) {
                if (rel.getType() == RelationshipType.EXTENDS || rel.getType() == RelationshipType.IMPLEMENTS) {
                    String interfaceName = rel.getTargetClass();
                    
                    // Check if this is a common repository interface pattern
                    if (interfaceName.contains("Repository") || interfaceName.contains("CrudRepository") ||
                        interfaceName.contains("JpaRepository") || interfaceName.contains("PagingAndSortingRepository") ||
                        interfaceName.contains("MongoRepository") || interfaceName.contains("ReactiveRepository")) {
                        // This is likely a Spring Data repository interface
                        isStandardRepositoryInterface = true;
                        System.out.println("Identified standard repository interface: " + interfaceName + " for " + repoClassName);
                        
                        // Mark as Repository in metadata if not already done
                        ClassDetails details = graph.getClassDetail(repoClassName);
                        if (details != null && details.getMetadata("role") == null) {
                            details.addMetadata("role", "Repository");
                        }
                    }
                    
                    // Check if this is a common repository interface pattern with generics
                    // Look for the actual relationship statement which might contain generic info
                    String fullKey = repoClassName + ":" + rel.getType().toString() + ":" + interfaceName;
                    Set<String> statements = relationshipStatements.get(fullKey);
                    if (statements != null) {
                        for (String statement : statements) {
                            // Look for patterns like "extends Repository<Owner, Integer>"
                            if (statement.contains("<") && statement.contains(">")) {
                                int startGeneric = statement.indexOf('<');
                                int endGeneric = statement.lastIndexOf('>');
                                
                                if (startGeneric > 0 && endGeneric > startGeneric) {
                                    // Extract the content between < and >
                                    String genericParams = statement.substring(startGeneric + 1, endGeneric);
                                    
                                    // Split by comma to get the first parameter (entity class)
                                    String[] params = genericParams.split(",");
                                    if (params.length > 0) {
                                        String entityClass = params[0].trim();
                                        
                                        // Resolve the entity class name if needed
                                        String resolvedEntity = resolveClassName(entityClass);
                                        
                                        if (isUserDefinedClass(resolvedEntity) && isValidClassName(resolvedEntity)) {
                                            result.add(resolvedEntity);
                                            System.out.println("Found entity " + resolvedEntity + 
                                                " from extends/implements statement: " + statement);
                                            
                                            // Mark the entity class as an Entity in metadata
                                            ClassDetails entityDetails = graph.getClassDetail(resolvedEntity);
                                            if (entityDetails != null && entityDetails.getMetadata("role") == null) {
                                                entityDetails.addMetadata("role", "Entity");
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
            
            // If we identified a standard repository interface but couldn't find entity through generics,
            // we could try other heuristics specifically for Spring Data repositories
            if (isStandardRepositoryInterface && result.isEmpty()) {
                System.out.println("Identified as standard repository but couldn't extract entity from generics: " + repoClassName);
                // Could apply additional Spring Data specific heuristics here
            }
        }
        
        // If no entities found using the standard pattern, check if there's a naming convention match
        if (result.isEmpty()) {
            String repoSimpleName = repoClassName;
            if (repoClassName.contains(".")) {
                repoSimpleName = repoClassName.substring(repoClassName.lastIndexOf('.') + 1);
            }
            
            if (repoSimpleName.endsWith("Repository") || repoSimpleName.endsWith("Dao") || 
                repoSimpleName.endsWith("Mapper")) {
                // Extract the entity name from the repository name as a fallback
                String entityName = null;
                
                if (repoSimpleName.endsWith("Repository")) {
                    entityName = repoSimpleName.substring(0, repoSimpleName.length() - "Repository".length());
                } else if (repoSimpleName.endsWith("Dao")) {
                    entityName = repoSimpleName.substring(0, repoSimpleName.length() - "Dao".length());
                } else if (repoSimpleName.endsWith("Mapper")) {
                    entityName = repoSimpleName.substring(0, repoSimpleName.length() - "Mapper".length());
                }
                
                if (entityName != null && !entityName.isEmpty()) {
                    // Look for this entity in our classes (in the same package or imported)
                    String packageName = "";
                    if (repoClassName.contains(".")) {
                        packageName = repoClassName.substring(0, repoClassName.lastIndexOf('.') + 1);
                    }
                    
                    String potentialEntityName = packageName + entityName;
                    
                    // Check if this class exists
                    if (userDefinedClasses.contains(potentialEntityName)) {
                        result.add(potentialEntityName);
                        System.out.println("Found entity " + potentialEntityName + " by naming convention (fallback)");
                        
                        // Mark the entity class as an Entity in metadata
                        ClassDetails entityDetails = graph.getClassDetail(potentialEntityName);
                        if (entityDetails != null && entityDetails.getMetadata("role") == null) {
                            entityDetails.addMetadata("role", "Entity");
                        }
                    }
                }
            }
        }
        
        return result;
    }
    
    /**
     * Resolve imports to get full class names
     */
    private void resolveImports() {
        // For each class, try to resolve any unresolved relationships using imports
        for (ClassNode node : graph.getNodes().values()) {
            String className = node.getClassName();
            Set<String> imports = importsByClass.getOrDefault(className, Collections.emptySet());
            
            List<Relationship> resolvedRelationships = new ArrayList<>();
            for (Relationship rel : node.getRelationships()) {
                String targetClass = rel.getTargetClass();
                
                // If the target class doesn't have a package (not fully qualified)
                if (!targetClass.contains(".") && !isBuiltInType(targetClass)) {
                    // Try to find a matching import
                    String resolvedClass = null;
                    
                    // First check for direct import
                    for (String importName : imports) {
                        if (importName.endsWith("." + targetClass)) {
                            resolvedClass = importName;
                            break;
                        }
                    }
                    
                    // If not found, check for wildcard imports
                    if (resolvedClass == null) {
                        for (String importName : imports) {
                            if (importName.endsWith(".*")) {
                                String packageName = importName.substring(0, importName.length() - 2);
                                String potentialClass = packageName + "." + targetClass;
                                
                                // Check if this class exists in our user-defined classes
                                if (userDefinedClasses.contains(potentialClass)) {
                                    resolvedClass = potentialClass;
                                    break;
                                }
                            }
                        }
                    }
                    
                    // If still not found, assume it's in the same package as the source class
                    if (resolvedClass == null) {
                        int lastDot = className.lastIndexOf('.');
                        if (lastDot > 0) {
                            String packageName = className.substring(0, lastDot);
                            resolvedClass = packageName + "." + targetClass;
                        } else {
                            // No package, use as is
                            resolvedClass = targetClass;
                        }
                    }
                    
                    // Create a new relationship with the resolved class name
                    resolvedRelationships.add(new Relationship(resolvedClass, rel.getType()));
                } else {
                    // Already fully qualified, keep as is
                    resolvedRelationships.add(rel);
                }
            }
            
            // Update the node with resolved relationships
            node.setRelationships(resolvedRelationships);
        }
        
        System.out.println("Resolved imports for class relationships");
    }
    
    /**
     * Check if a type is a built-in Java type
     */
    private boolean isBuiltInType(String typeName) {
        return typeName.equals("void") || typeName.equals("int") || typeName.equals("boolean") ||
               typeName.equals("long") || typeName.equals("double") || typeName.equals("float") ||
               typeName.equals("char") || typeName.equals("byte") || typeName.equals("short") ||
               typeName.equals("Object") || typeName.equals("String") || typeName.equals("Class") ||
               typeName.equals("Exception") || typeName.equals("RuntimeException") ||
               typeName.equals("Throwable") || typeName.equals("Error") || typeName.equals("Enum") ||
               typeName.equals("Thread") || typeName.equals("Runnable") || typeName.equals("Cloneable") ||
               typeName.equals("Comparable") || typeName.equals("Serializable") ||
               typeName.equals("Number") || typeName.equals("Integer") || typeName.equals("Long") ||
               typeName.equals("Double") || typeName.equals("Float") || typeName.equals("Boolean") ||
               typeName.equals("Character") || typeName.equals("Byte") || typeName.equals("Short") ||
               typeName.equals("Void");
    }
    
    /**
     * Print the detected relationships
     */
    public void printRelationships() {
        System.out.println("Class Relationships:");
        System.out.println("===================");
        
        graph.getNodes().forEach((className, node) -> {
            System.out.println(className + ":");
            List<Relationship> relationships = node.getRelationships();
            if (relationships.isEmpty()) {
                System.out.println("  No relationships");
            } else {
                relationships.forEach(rel -> {
                    System.out.println("  " + rel.getType() + " -> " + rel.getTargetClass());
                });
            }
            System.out.println();
        });
    }
    
    /**
     * Export the relationships to a JSON file
     */
    public void exportToJson(String outputFile) {
        try {
            ObjectMapper mapper = new ObjectMapper();
            mapper.enable(SerializationFeature.INDENT_OUTPUT);
            
            // Create a map for JSON serialization
            Map<String, Object> data = new HashMap<>();
            
            // Add simplified metadata
            Map<String, Object> metadata = new HashMap<>();
            metadata.put("totalClasses", graph.getNodes().size());
            
            // Count relationships by type
            Map<String, Integer> relationshipCounts = new HashMap<>();
            Map<String, Integer> relationshipTotalOccurrences = new HashMap<>();
            
            for (ClassNode node : graph.getNodes().values()) {
                for (Relationship rel : node.getRelationships()) {
                    // Count unique relationships
                    relationshipCounts.merge(rel.getType().toString(), 1, Integer::sum);
                    
                    // Count total occurrences including repeated relationships
                    relationshipTotalOccurrences.merge(rel.getType().toString(), rel.getCount(), Integer::sum);
                }
            }
            
            metadata.put("relationshipCounts", relationshipCounts);
            metadata.put("relationshipTotalOccurrences", relationshipTotalOccurrences);
            
            data.put("metadata", metadata);
            
            // Convert graph nodes to a format suitable for JSON
            // Rearranged to prioritize class names first
            Map<String, Object> classMap = new LinkedHashMap<>();
            
            // Sort classes by name for consistent output
            List<String> sortedClassNames = new ArrayList<>(graph.getNodes().keySet());
            Collections.sort(sortedClassNames);
            
            // First pass: collect all direct relationships
            // Structure: targetClass -> inverseRelationType -> sourceClass -> count
            Map<String, Map<String, Map<String, Integer>>> inverseRelationships = new HashMap<>();
            
            // Initialize inverse relationships map for all classes
            for (String className : sortedClassNames) {
                inverseRelationships.put(className, new HashMap<>());
            }
            
            // Collect inverse relationships
            for (String className : sortedClassNames) {
                ClassNode node = graph.getNodes().get(className);
                
                // Count relationships by target and type
                Map<String, Map<RelationshipType, Integer>> targetTypeCounts = new HashMap<>();
                
                // First gather all relationships and count them
                for (Relationship rel : node.getRelationships()) {
                    String targetClass = rel.getTargetClass();
                    RelationshipType type = rel.getType();
                    
                    // Count this relationship using the actual count
                    targetTypeCounts
                        .computeIfAbsent(targetClass, k -> new HashMap<>())
                        .merge(type, rel.getCount(), Integer::sum);
                }
                
                // Now create inverse relationships with proper counts
                for (Map.Entry<String, Map<RelationshipType, Integer>> entry : targetTypeCounts.entrySet()) {
                    String targetClass = entry.getKey();
                    Map<RelationshipType, Integer> typeCounts = entry.getValue();
                    
                    for (Map.Entry<RelationshipType, Integer> typeEntry : typeCounts.entrySet()) {
                        RelationshipType type = typeEntry.getKey();
                        Integer count = typeEntry.getValue();
                        String relType = type.toString();
                        String inverseType = getInverseRelationshipType(relType);
                        
                        // Add inverse relationship to target class with the same count
                        // Now properly grouped by inverse relationship type
                        if (inverseType != null && graph.getNodes().containsKey(targetClass)) {
                            inverseRelationships.get(targetClass)
                                .computeIfAbsent(inverseType, k -> new HashMap<>())
                                .put(className, count);
                        }
                    }
                }
            }
            
            // Second pass: create the JSON structure with both direct and inverse relationships
            for (String className : sortedClassNames) {
                ClassNode node = graph.getNodes().get(className);
                ClassDetails details = graph.getClassDetail(className);
                
                // Create the class object with all the information
                Map<String, Object> classData = new LinkedHashMap<>();
                
                // Add annotations
                if (details != null && !details.getAnnotations().isEmpty()) {
                    classData.put("annotations", details.getAnnotations());
                }
                
                // Add inner classes if present
                if (details != null && !details.getInnerClasses().isEmpty()) {
                    Map<String, Object> innerClassesData = new LinkedHashMap<>();
                    for (String innerClassName : details.getInnerClasses()) {
                        Map<String, Object> innerClassData = new LinkedHashMap<>();
                        
                        // Add inner class annotations if any
                        List<String> innerClassAnnotations = details.getInnerClassAnnotations(innerClassName);
                        if (innerClassAnnotations != null && !innerClassAnnotations.isEmpty()) {
                            innerClassData.put("annotations", innerClassAnnotations);
                        }
                        
                        innerClassesData.put(innerClassName, innerClassData);
                    }
                    classData.put("innerClasses", innerClassesData);
                }
                
                // Add methods
                if (details != null && !details.getMethods().isEmpty()) {
                    List<Map<String, Object>> methodsData = new ArrayList<>();
                    for (MethodInfo method : details.getMethods()) {
                        Map<String, Object> methodData = new LinkedHashMap<>();
                        methodData.put("signature", method.getSignature());
                        if (!method.getAnnotations().isEmpty()) {
                            methodData.put("annotations", method.getAnnotations());
                        }
                        methodsData.add(methodData);
                    }
                    classData.put("methods", methodsData);
                }
                
                // Add fields
                if (details != null && !details.getFields().isEmpty()) {
                    List<Map<String, Object>> fieldsData = new ArrayList<>();
                    for (FieldInfo field : details.getFields()) {
                        Map<String, Object> fieldData = new LinkedHashMap<>();
                        fieldData.put("declaration", field.getDeclaration());
                        if (!field.getAnnotations().isEmpty()) {
                            fieldData.put("annotations", field.getAnnotations());
                        }
                        fieldsData.add(fieldData);
                    }
                    classData.put("fields", fieldsData);
                }
                
                // Group relationships by type
                Map<String, Map<String, Integer>> relationshipsByType = new HashMap<>();
                
                // Count direct relationships by target class and type
                for (Relationship rel : node.getRelationships()) {
                    String relType = rel.getType().toString();
                    String targetClass = rel.getTargetClass();
                    
                    // Add count for this relationship (use actual count instead of 1)
                    relationshipsByType
                        .computeIfAbsent(relType, k -> new HashMap<>())
                        .put(targetClass, rel.getCount());
                }
                
                // Add inverse relationships
                // inverseRelationships structure: targetClass -> inverseRelationType -> sourceClass -> count
                Map<String, Map<String, Integer>> inverseRels = inverseRelationships.get(className);
                if (inverseRels != null) {
                    for (Map.Entry<String, Map<String, Integer>> typeEntry : inverseRels.entrySet()) {
                        String inverseType = typeEntry.getKey();
                        Map<String, Integer> sourceClassCounts = typeEntry.getValue();
                        
                        for (Map.Entry<String, Integer> sourceEntry : sourceClassCounts.entrySet()) {
                            String sourceClass = sourceEntry.getKey();
                            Integer count = sourceEntry.getValue();
                            
                            relationshipsByType
                                .computeIfAbsent(inverseType, k -> new HashMap<>())
                                .put(sourceClass, count);
                        }
                    }
                }
                
                // Add relationships (even if empty)
                classData.put("relationships", relationshipsByType);
                
                // Add the class data to the class map
                classMap.put(className, classData);
            }
            
            data.put("classes", classMap);
            
            // Write to file
            mapper.writeValue(new File(outputFile), data);
            System.out.println("Relationships exported to: " + outputFile);
        } catch (IOException e) {
            System.err.println("Error exporting relationships to JSON: " + e.getMessage());
        }
    }
    
    /**
     * Get the relationship type between two classes
     */
    private String getRelationshipTypeFromClasses(String sourceClass, String targetClass) {
        ClassNode sourceNode = graph.getNodes().get(sourceClass);
        if (sourceNode != null) {
            for (Relationship rel : sourceNode.getRelationships()) {
                if (rel.getTargetClass().equals(targetClass)) {
                    return rel.getType().toString();
                }
            }
        }
        return null;
    }
    
    /**
     * Get the inverse relationship type for a given relationship type
     */
    private String getInverseRelationshipType(String relType) {
        switch (relType) {
            case "USES":
                return "USED_BY";
            case "CREATES":
                return "CREATED_BY";
            case "CALLS":
                return "CALLED_BY";
            case "EXTENDS":
                return "EXTENDED_BY";
            case "IMPLEMENTS":
                return "IMPLEMENTED_BY";
            case "ASSOCIATES":
                return "ASSOCIATED_WITH";
            case "INJECTS":
                return "INJECTED_BY";
            case "ANNOTATED_WITH":
                return "ANNOTATES";
            case "REFERENCES":
                return "REFERENCED_BY";
            case "DEPENDS_ON":
                return "DEPENDENCY_OF";
            case "PERSISTS":
                return "PERSISTED_BY";
            default:
                return null;
        }
    }
    
    /**
     * Resolve class name to fully qualified name if possible
     */
    private String resolveClassName(String className) {
        // Primitive types don't need resolution
        if (className == null || className.isEmpty() || 
            className.equals("void") || className.equals("int") || className.equals("boolean") ||
            className.equals("long") || className.equals("double") || className.equals("float") ||
            className.equals("char") || className.equals("byte") || className.equals("short")) {
            return className;
        }
        
        // Check if it's already fully qualified
        if (className.contains(".")) {
            return className;
        }
        
        // Try to find in user-defined classes with package name
        for (String fullClassName : userDefinedClasses) {
            if (fullClassName.endsWith("." + className)) {
                return fullClassName;
            }
        }
        
        // Try to find in imports from any class that might have imported it
        for (Map.Entry<String, Set<String>> entry : importsByClass.entrySet()) {
            Set<String> imports = entry.getValue();
            for (String importName : imports) {
                if (importName.endsWith("." + className)) {
                    return importName;
                }
            }
        }
        
        // If not found and it's a simple name that looks like a class, 
        // we'll return null to indicate it couldn't be resolved to a fully qualified name
        if (Character.isUpperCase(className.charAt(0))) {
            // Check if it's a common Java class
            String[] commonJavaClasses = {"String", "Integer", "Boolean", "Long", "Double", 
                                         "Object", "Class", "Exception", "RuntimeException",
                                         "Error", "Throwable", "ClassLoader", "IllegalArgumentException",
                                         "StringBuilder", "StringBuffer", "Enum", "Comparable",
                                         "Serializable", "Cloneable", "Thread", "Runnable",
                                         "Number", "Byte", "Short", "Character", "Float", "Void"};
            for (String javaClass : commonJavaClasses) {
                if (className.equals(javaClass)) {
                    return "java.lang." + className; // Return standard java.lang package for common classes
                }
            }
            
            return null; // Could not resolve to a fully qualified name
        }
        
        // Not a class name (likely a variable name)
        return null;
    }
    
    /**
     * Extract the base type from a generic type expression
     * For example, "List<String>" becomes "List"
     */
    private String extractBaseType(String genericType) {
        if (genericType == null) {
            return null;
        }
        
        int genericStart = genericType.indexOf('<');
        if (genericStart > 0) {
            return genericType.substring(0, genericStart);
        }
        return genericType;
    }
    
    /**
     * Check if a name is likely to be a valid class name
     */
    private boolean isValidClassName(String name) {
        // Class name must be a valid identifier
        if (name == null || name.isEmpty()) {
            return false;
        }
        
        // Already checked by isUserDefinedClass, but being extra safe
        if (name.contains("<") || name.contains(">")) {
            return false;
        }
        
        // Extract simple name if it has a package
        String simpleName = name.contains(".") ? 
            name.substring(name.lastIndexOf('.') + 1) : name;
        
        // Java class names are typically uppercase
        if (!Character.isUpperCase(simpleName.charAt(0))) {
            return false;
        }
        
        // Filter out common non-class patterns
        return isUserDefinedClass(name);
    }
    
    /**
     * Visitor to analyze relationships between classes
     * Enhanced with CHA algorithm for method call analysis
     */
    private class RelationshipVisitor extends VoidVisitorAdapter<Void> {
        private final String sourceClass;
        private final String packageName;
        // Map to track local variable types within the current method
        private final Map<String, String> localVariableTypes = new HashMap<>();
        // Set to track relationships already added in the current method (to avoid duplicates)
        // No longer used as we now count all relationships
        private final Set<String> addedRelationships = new HashSet<>();
        
        public RelationshipVisitor(String sourceClass, String packageName) {
            this.sourceClass = sourceClass;
            this.packageName = packageName;
        }
        
        @Override
        public void visit(ClassOrInterfaceDeclaration cls, Void arg) {
            // Clear tracking maps when entering a new class
            localVariableTypes.clear();
            addedRelationships.clear();
            
            // // Check for extends relationship
            // for (ClassOrInterfaceType extendedType : cls.getExtendedTypes()) {
            //     String targetClass = resolveClassName(extendedType.getNameAsString());
            //     if (isUserDefinedClass(targetClass)) {
            //         addRelationshipOnce(targetClass, RelationshipType.EXTENDS, 
            //             cls.getNameAsString() + " extends " + extendedType.getNameAsString());
            //     }
            // }
            
            // // Check for implements relationship
            // for (ClassOrInterfaceType implementedType : cls.getImplementedTypes()) {
            //     String targetClass = resolveClassName(implementedType.getNameAsString());
            //     if (isUserDefinedClass(targetClass)) {
            //         addRelationshipOnce(targetClass, RelationshipType.IMPLEMENTS, 
            //             cls.getNameAsString() + " implements " + implementedType.getNameAsString());
            //     }
            // }
            
            // Check for annotations
            for (AnnotationExpr annotation : cls.getAnnotations()) {
                String targetClass = resolveClassName(annotation.getNameAsString());
                String annotationName = annotation.getNameAsString();
                
                if (!isUserDefinedClass(targetClass)) {
                    continue;
                }
                
                // Special handling for Spring and Java EE annotations
                if (annotationName.contains("Inject") || annotationName.contains("Autowired")) {
                    // This class uses dependency injection
                    // We will identify actual injection relationships when processing fields
                } else if (annotationName.contains("Entity") || annotationName.contains("Table") ||
                           annotationName.contains("Embeddable") || annotationName.contains("MappedSuperclass")) {
                    // This is a JPA entity or other association-related class
                    // Mark this class as an entity for later repository relationship analysis
                    ClassDetails classDetails = graph.getClassDetail(sourceClass);
                    if (classDetails != null) {
                        classDetails.addMetadata("role", "Entity");
                    }
                } else if (annotationName.contains("Repository")) {
                    // This is a repository component that likely persists entities
                    ClassDetails classDetails = graph.getClassDetail(sourceClass);
                    if (classDetails != null) {
                        classDetails.addMetadata("role", "Repository");
                    }
                    // Repository relationships will be analyzed by examining methods and generic parameters
                } else if (annotationName.contains("Controller") || annotationName.contains("Service") 
                        || annotationName.contains("Component")) {
                    // This is a Spring component
                    ClassDetails classDetails = graph.getClassDetail(sourceClass);
                    if (classDetails != null) {
                        classDetails.addMetadata("role", annotationName.contains("Controller") ? "Controller" : 
                                                annotationName.contains("Service") ? "Service" : "Component");
                    }
                } else {
                    addRelationshipOnce(targetClass, RelationshipType.ANNOTATED_WITH, 
                        "@" + annotationName + " " + cls.getNameAsString());
                }
            }
            
            // Visit members
            super.visit(cls, arg);
        }
        
        @Override
        public void visit(FieldDeclaration field, Void arg) {
            // For each variable declared in this field declaration
            for (VariableDeclarator variable : field.getVariables()) {
                // Create field info object
                String fieldName = variable.getNameAsString();
                String originalType = variable.getType().asString(); // Get the original type as it appears in source
                String resolvedType = resolveClassName(originalType); // Get the fully qualified type
                FieldInfo fieldInfo = new FieldInfo(fieldName, resolvedType, originalType);
                
                // Set field modifiers
                fieldInfo.setPrivate(field.isPrivate());
                fieldInfo.setPublic(field.isPublic());
                fieldInfo.setProtected(field.isProtected());
                fieldInfo.setStatic(field.isStatic());
                fieldInfo.setFinal(field.isFinal());
                
                // Add field annotations
                for (AnnotationExpr annotation : field.getAnnotations()) {
                    fieldInfo.addAnnotation(annotation.toString());
                }
                
                // Add field to class details
                ClassDetails classDetails = graph.getClassDetail(sourceClass);
                if (classDetails != null) {
                    classDetails.addField(fieldInfo);
                }
            
                // Get field type for relationship analysis
                String typeName = resolveClassName(field.getElementType().asString());
                
                // Check for collection or map types that might contain entity references
                boolean isCollection = false;
                String collectionElementType = null;
                
                // Check if this is a collection type with generic parameters
                try {
                    if (field.getElementType().asString().contains("<")) {
                        String rawType = field.getElementType().asString();
                        
                        // Handle common collection types
                        if (rawType.startsWith("List<") || rawType.startsWith("Set<") || 
                            rawType.startsWith("Collection<") || rawType.startsWith("Iterable<")) {
                            isCollection = true;
                            // Extract the generic type parameter
                            int startIndex = rawType.indexOf('<') + 1;
                            int endIndex = rawType.lastIndexOf('>');
                            if (startIndex > 0 && endIndex > startIndex) {
                                String genericParam = rawType.substring(startIndex, endIndex).trim();
                                collectionElementType = resolveClassName(genericParam);
                                
                                // Validate that this is actually a class, not a variable or parameter
                                if (!isValidClassName(collectionElementType)) {
                                    collectionElementType = null;
                                }
                            }
                        }
                        // Handle Map types
                        else if (rawType.startsWith("Map<")) {
                            isCollection = true;
                            // Extract the value type parameter (the second one)
                            int commaIndex = rawType.indexOf(',');
                            int endIndex = rawType.lastIndexOf('>');
                            if (commaIndex > 0 && endIndex > commaIndex) {
                                String genericParam = rawType.substring(commaIndex + 1, endIndex).trim();
                                collectionElementType = resolveClassName(genericParam);
                                
                                // Validate that this is actually a class
                                if (!isValidClassName(collectionElementType)) {
                                    collectionElementType = null;
                                }
                            }
                        }
                        
                        // Use the base type instead of full generic expression for type relationships
                        String baseType = extractBaseType(rawType);
                        if (baseType != null && !baseType.equals(rawType)) {
                            typeName = resolveClassName(baseType);
                        }
                    }
                } catch (Exception e) {
                    // If we can't parse the generic type, just continue with regular analysis
                    System.err.println("Warning: Could not parse generic type for field: " + field);
                }
                
                // Basic type use relationship
                if (isUserDefinedClass(typeName)) {
                    addRelationshipOnce(typeName, RelationshipType.USES, 
                        field.getElementType().asString() + " " + fieldName);
                }
                
                // If this is a collection of entities, also add USES relationship to the element type
                if (isCollection && collectionElementType != null && isUserDefinedClass(collectionElementType)) {
                    addRelationshipOnce(collectionElementType, RelationshipType.USES, 
                        field.getElementType().asString() + " " + fieldName);
                }
            
                // Check for Spring injections
                boolean isInjected = false;
                for (AnnotationExpr annotation : field.getAnnotations()) {
                    String annotationName = annotation.getNameAsString();
                    if (annotationName.contains("Autowired") || annotationName.contains("Inject") ||
                        annotationName.contains("Resource") || annotationName.contains("Value")) {
                        isInjected = true;
                        break;
                    }
                }
                
                if (isInjected) {
                    if (isUserDefinedClass(typeName)) {
                        addRelationshipOnce(typeName, RelationshipType.INJECTS, 
                            "@Inject " + field.getElementType().asString() + " " + fieldName);
                        
                        // Also track component roles for better understanding of the architecture
                        ClassDetails sourceDetails = graph.getClassDetail(sourceClass);
                        ClassDetails targetDetails = graph.getClassDetail(typeName);
                        
                        if (sourceDetails != null && targetDetails != null) {
                            // Ensure roles are properly tracked in metadata
                            String sourceRole = sourceDetails.getMetadata("role");
                            String targetRole = targetDetails.getMetadata("role");
                            
                            // Update source role if it's not set but can be inferred
                            if (sourceRole == null) {
                                if (sourceClass.contains("Controller")) {
                                    sourceDetails.addMetadata("role", "Controller");
                                } else if (sourceClass.contains("Service")) {
                                    sourceDetails.addMetadata("role", "Service");
                                } else if (sourceClass.contains("Repository") || sourceClass.contains("Dao") || sourceClass.contains("Mapper")) {
                                    sourceDetails.addMetadata("role", "Repository");
                                }
                            }
                            
                            // Update target role if it's not set but can be inferred
                            if (targetRole == null) {
                                if (typeName.contains("Service")) {
                                    targetDetails.addMetadata("role", "Service");
                                } else if (typeName.contains("Repository") || typeName.contains("Dao") || typeName.contains("Mapper")) {
                                    targetDetails.addMetadata("role", "Repository");
                                }
                            }
                            
                            // Note: As per previous discussion, we don't add CALLS relationship
                            // for Controller->Service or Service->Repository as it's captured by INJECTS
                        }
                    }
                    
                    // Also add INJECTS for collection element types
                    if (isCollection && collectionElementType != null && isUserDefinedClass(collectionElementType)) {
                        addRelationshipOnce(collectionElementType, RelationshipType.INJECTS, 
                            "@Inject " + field.getElementType().asString() + " " + fieldName);
                    }
                }
            
                // Check for JPA relationships
                boolean isAssociationRelationship = false;
                boolean fieldHasAssociationAnnotation = false;
                
                for (AnnotationExpr annotation : field.getAnnotations()) {
                    String annotationName = annotation.getNameAsString();
                    
                    // Direct relationship annotations
                    if (annotationName.contains("OneToMany") || annotationName.contains("ManyToOne") ||
                        annotationName.contains("OneToOne") || annotationName.contains("ManyToMany") ||
                        annotationName.contains("JoinColumn") || annotationName.contains("JoinTable") ||
                        annotationName.contains("JoinColumns") || annotationName.contains("MapKey") ||
                        annotationName.contains("OrderColumn")) {
                        isAssociationRelationship = true;
                        fieldHasAssociationAnnotation = true;
                    }
                    
                    // Other association-related field annotations
                    else if (annotationName.contains("Column") || annotationName.contains("Basic") ||
                             annotationName.contains("Id") || annotationName.contains("GeneratedValue") ||
                             annotationName.contains("Embedded") || annotationName.contains("ElementCollection") ||
                             annotationName.contains("Enumerated") || annotationName.contains("Temporal") ||
                             annotationName.contains("Lob") || annotationName.contains("Transient") ||
                             annotationName.contains("Version") || annotationName.contains("OrderBy")) {
                        fieldHasAssociationAnnotation = true;
                    }
                }
                
                // Check if the current class is a JPA entity
                boolean isInEntityClass = false;
                ClassDetails currentClassDetails = graph.getClassDetail(sourceClass);
                if (currentClassDetails != null) {
                    String role = currentClassDetails.getMetadata("role");
                    isInEntityClass = "Entity".equals(role);
                    
                    if (!isInEntityClass) {
                    for (String annotation : currentClassDetails.getAnnotations()) {
                        if (annotation.contains("Entity") || annotation.contains("Embeddable") || 
                            annotation.contains("MappedSuperclass")) {
                            isInEntityClass = true;
                                currentClassDetails.addMetadata("role", "Entity");
                            break;
                            }
                        }
                    }
                }
                
                // If the field type matches certain patterns, it's likely an association relationship
                // even without explicit annotations
                if (!isAssociationRelationship && (fieldHasAssociationAnnotation || isInEntityClass)) {
                    // Check field type and name for common association patterns
                    String fieldNameLower = fieldName.toLowerCase();
                    
                    if (isCollection) {
                        // Collections in entities are often relationships
                        if (collectionElementType != null && isUserDefinedClass(collectionElementType)) {
                            isAssociationRelationship = true;
                        }
                    } else if (isUserDefinedClass(typeName)) {
                        // Field named "id" + className is likely a foreign key
                        if (fieldNameLower.endsWith("id") || fieldNameLower.contains("_id")) {
                            isAssociationRelationship = true;
                        }
                        // Field named after another entity is likely a relationship
                        else if (typeName.endsWith(fieldName)) {
                            isAssociationRelationship = true;
                        }
                        // In an entity class, fields of other user-defined types are likely relationships
                        else if (isInEntityClass) {
                            isAssociationRelationship = true;
                        }
                    }
                }
                
                // Add ASSOCIATES relationship if we found any JPA relationship indicators
                if (isAssociationRelationship) {
                    if (isCollection && collectionElementType != null && isUserDefinedClass(collectionElementType)) {
                        // For collections, the relationship is to the element type
                        addRelationshipOnce(collectionElementType, RelationshipType.ASSOCIATES, 
                            "@Entity " + field.getElementType().asString() + " " + fieldName);
                    } else if (isUserDefinedClass(typeName)) {
                        // For direct references, the relationship is to the field type
                        addRelationshipOnce(typeName, RelationshipType.ASSOCIATES, 
                            "@Entity " + field.getElementType().asString() + " " + fieldName);
                    }
                }
            }
            
            super.visit(field, arg);
        }
        
        @Override
        public void visit(MethodDeclaration method, Void arg) {
            // Clear tracking maps when entering a new method
            localVariableTypes.clear();
            // addedRelationships.clear(); // No longer needed as we count all relationships
            
            // Track parameter types
            method.getParameters().forEach(param -> {
                String paramName = param.getNameAsString();
                String paramType = resolveClassName(param.getType().asString());
                localVariableTypes.put(paramName, paramType);
            });
            
            // Check return type (USES)
            String returnType = resolveClassName(method.getType().asString());
            if (isUserDefinedClass(returnType)) {
                addRelationshipOnce(returnType, RelationshipType.USES, 
                    method.getType().asString() + " " + method.getNameAsString() + "()");
            }
            
            // Check parameters (USES)
            method.getParameters().forEach(param -> {
                String paramType = resolveClassName(param.getType().asString());
                if (isUserDefinedClass(paramType)) {
                    addRelationshipOnce(paramType, RelationshipType.USES, 
                        param.getType().asString() + " " + param.getNameAsString());
                }
            });
            
            // Check for JPA annotations on methods (like getters/setters)
            boolean isAssociationMethod = false;
            boolean isRelationshipMethod = false;
            String relationshipType = null;
            
            // JPA sometimes uses annotations on getter methods instead of fields
            for (AnnotationExpr annotation : method.getAnnotations()) {
                String annotationName = annotation.getNameAsString();
                
                // Direct relationship annotations
                if (annotationName.contains("OneToMany") || annotationName.contains("ManyToOne") ||
                    annotationName.contains("OneToOne") || annotationName.contains("ManyToMany") ||
                    annotationName.contains("JoinColumn") || annotationName.contains("JoinTable") ||
                    annotationName.contains("JoinColumns") || annotationName.contains("MapKey") ||
                    annotationName.contains("OrderColumn")) {
                    isAssociationMethod = true;
                    isRelationshipMethod = true;
                }
                
                // Other association-related field annotations
                else if (annotationName.contains("Column") || annotationName.contains("Basic") ||
                         annotationName.contains("Id") || annotationName.contains("GeneratedValue") ||
                         annotationName.contains("Embedded") || annotationName.contains("ElementCollection") ||
                         annotationName.contains("Enumerated") || annotationName.contains("Temporal") ||
                         annotationName.contains("Lob") || annotationName.contains("Transient") ||
                         annotationName.contains("Version") || annotationName.contains("OrderBy")) {
                    isAssociationMethod = true;
                }
            }
            
            // If this is a getter/setter method with association annotations
            if (isAssociationMethod) {
                // Check if it's a getter method
                if ((method.getNameAsString().startsWith("get") || method.getNameAsString().startsWith("is")) && method.getParameters().isEmpty()) {
                    // For getters, check the return type
                    if (isRelationshipMethod && isUserDefinedClass(returnType)) {
                        // This is a getter for a relationship
                        addRelationshipOnce(returnType, RelationshipType.ASSOCIATES, 
                            "@Entity " + method.getType().asString() + " " + method.getNameAsString() + "()");
                    }
                    
                    // Check if the return type is a collection
                    boolean isCollection = false;
                    String collectionElementType = null;
                    
                    try {
                        if (returnType.contains("<")) {
                            String rawType = returnType;
                            
                            // Handle common collection types
                            if (rawType.startsWith("List<") || rawType.startsWith("Set<") || 
                                rawType.startsWith("Collection<") || rawType.startsWith("Iterable<")) {
                                isCollection = true;
                                // Extract the generic type parameter
                                int startIndex = rawType.indexOf('<') + 1;
                                int endIndex = rawType.lastIndexOf('>');
                                if (startIndex > 0 && endIndex > startIndex) {
                                    collectionElementType = resolveClassName(
                                        rawType.substring(startIndex, endIndex).trim());
                                }
                            }
                            // Handle Map types
                            else if (rawType.startsWith("Map<")) {
                                isCollection = true;
                                // Extract the value type parameter (the second one)
                                int commaIndex = rawType.indexOf(',');
                                int endIndex = rawType.lastIndexOf('>');
                                if (commaIndex > 0 && endIndex > commaIndex) {
                                    collectionElementType = resolveClassName(
                                        rawType.substring(commaIndex + 1, endIndex).trim());
                                }
                            }
                            
                            // If this is a collection getter with relationship annotations
                            if (isRelationshipMethod && isCollection && 
                                collectionElementType != null && isUserDefinedClass(collectionElementType)) {
                                addRelationshipOnce(collectionElementType, RelationshipType.ASSOCIATES, 
                                    "@Entity " + method.getType().asString() + " " + method.getNameAsString() + "()");
                            }
                        }
                    } catch (Exception e) {
                        // If we can't parse the generic type, just continue
                        System.err.println("Warning: Could not parse generic return type for method: " + method);
                    }
                }
            }
            
            // Visit method body
            super.visit(method, arg);
        }
        
        @Override
        public void visit(MethodCallExpr methodCall, Void arg) {
            // 恢复对方法调用的处理，以处理嵌套的方法调用
            // 但不处理作为语句的顶层方法调用（那些会在ExpressionStmt中处理）
            if (!(methodCall.getParentNode().isPresent() && 
                  methodCall.getParentNode().get() instanceof ExpressionStmt)) {
                processMethodCall(methodCall);
            }
            
            // 恢复super.visit调用，确保子节点被访问
            super.visit(methodCall, arg);
        }
        
        @Override
        public void visit(FieldAccessExpr fieldAccess, Void arg) {
            // 恢复对字段访问的处理，但避免重复处理
            // 只处理不是作为语句一部分的字段访问
            if (!(fieldAccess.getParentNode().isPresent() && 
                  fieldAccess.getParentNode().get() instanceof ExpressionStmt)) {
                processFieldAccess(fieldAccess);
            }
            
            // 恢复super.visit调用，确保子节点被访问
            super.visit(fieldAccess, arg);
        }
        
        @Override
        public void visit(VariableDeclarationExpr varDecl, Void arg) {
            // Handle local variable declarations within methods
            for (VariableDeclarator var : varDecl.getVariables()) {
                // Get the variable type and name
                String varName = var.getNameAsString();
                String originalType = var.getType().asString();
                
                // Process type to handle generics - extract the base type if it's a generic
                String typeToUse = originalType;
                if (originalType.contains("<")) {
                    String baseType = extractBaseType(originalType);
                    if (baseType != null && isValidClassName(baseType)) {
                        typeToUse = baseType;
                    }
                }
                
                String typeName = resolveClassName(typeToUse);
                
                // Track this variable's type but don't confuse variable names with class names
                localVariableTypes.put(varName, typeName);
                
                // Add USES relationship only if the type is a valid class
                if (isValidClassName(typeName) && isUserDefinedClass(typeName)) {
                    addRelationshipOnce(typeName, RelationshipType.USES, 
                        originalType + " " + varName);
                }
                
                // Check for collection or map types that might contain entity references
                boolean isCollection = false;
                String collectionElementType = null;
                
                // Check if this is a collection type with generic parameters
                try {
                    if (originalType.contains("<")) {
                        String rawType = originalType;
                        
                        // Handle common collection types
                        if (rawType.startsWith("List<") || rawType.startsWith("Set<") || 
                            rawType.startsWith("Collection<") || rawType.startsWith("Iterable<") ||
                            rawType.startsWith("Iterator<")) {  // Added Iterator<> support
                            isCollection = true;
                            // Extract the generic type parameter
                            int startIndex = rawType.indexOf('<') + 1;
                            int endIndex = rawType.lastIndexOf('>');
                            if (startIndex > 0 && endIndex > startIndex) {
                                String genericParam = rawType.substring(startIndex, endIndex).trim();
                                String resolvedParam = resolveClassName(genericParam);
                                
                                // Only if it's a valid class name
                                if (isValidClassName(resolvedParam)) {
                                    collectionElementType = resolvedParam;
                                
                                // For Iterator<T> and Iterable<T>, also track that the variable name
                                // will produce elements of type T when .next() is called
                                if (rawType.startsWith("Iterator<") || rawType.startsWith("Iterable<")) {
                                    // Store the element type for this iterator variable
                                    // so we can use it when processing .next() calls
                                    localVariableTypes.put(varName + ".element", collectionElementType);
                                    }
                                }
                            }
                        }
                        // Handle Map types
                        else if (rawType.startsWith("Map<")) {
                            isCollection = true;
                            // Extract the value type parameter (the second one)
                            int commaIndex = rawType.indexOf(',');
                            int endIndex = rawType.lastIndexOf('>');
                            if (commaIndex > 0 && endIndex > commaIndex) {
                                String genericParam = rawType.substring(commaIndex + 1, endIndex).trim();
                                String resolvedParam = resolveClassName(genericParam);
                                
                                // Only if it's a valid class name
                                if (isValidClassName(resolvedParam)) {
                                    collectionElementType = resolvedParam;
                                }
                            }
                        }
                    }
                } catch (Exception e) {
                    // If we can't parse the generic type, just continue with regular analysis
                    System.err.println("Warning: Could not parse generic type for variable: " + var);
                }
                
                // If this is a collection of entities, also add USES relationship to the element type
                if (isCollection && collectionElementType != null && isUserDefinedClass(collectionElementType)) {
                    addRelationshipOnce(collectionElementType, RelationshipType.USES, 
                        originalType + " " + varName);
                }
                
                // Check initializer for additional relationships
                if (var.getInitializer().isPresent()) {
                    Expression initializer = var.getInitializer().get();
                    
                    // Special handling for iterator.next() calls
                    if (initializer instanceof MethodCallExpr) {
                        MethodCallExpr methodCall = (MethodCallExpr) initializer;
                        if (methodCall.getNameAsString().equals("next") && 
                            methodCall.getScope().isPresent() && 
                            methodCall.getScope().get().isNameExpr()) {
                            
                            String iteratorName = methodCall.getScope().get().toString();
                            String elementType = localVariableTypes.get(iteratorName + ".element");
                            
                            if (elementType != null && isUserDefinedClass(elementType)) {
                                // This is an iterator.next() call, and we know the element type
                                // Add a relationship to the element type
                                addRelationshipOnce(elementType, RelationshipType.USES, 
                                    var.getType().asString() + " " + varName + " = " + iteratorName + ".next()");
                                
                                // Also update this variable's type to be the element type
                                localVariableTypes.put(varName, elementType);
                            }
                        }
                    }
                    
                    /* 注释掉递归处理，让JavaParser的访问者模式来处理
                    // If initializing with a new object
                    if (initializer instanceof ObjectCreationExpr) {
                        processObjectCreation((ObjectCreationExpr) initializer);
                    }
                    // If initializing with a method call
                    else if (initializer instanceof MethodCallExpr) {
                        processMethodCall((MethodCallExpr) initializer);
                    }
                    // If initializing with a field access
                    else if (initializer instanceof FieldAccessExpr) {
                        processFieldAccess((FieldAccessExpr) initializer);
                    }
                    // If initializing with a cast
                    else if (initializer instanceof CastExpr) {
                        processCastExpr((CastExpr) initializer);
                    }
                    */
                    // 对于变量初始化表达式中的嵌套表达式，它们会在各自的visit方法中处理
                    // 不需要手动调用initializer.accept，super.visit会处理
                }
            }
            
            // 恢复super.visit调用，确保子节点被访问
            super.visit(varDecl, arg);
        }
        
        @Override
        public void visit(ReturnStmt returnStmt, Void arg) {
            // Check if the return statement has an expression
            if (returnStmt.getExpression().isPresent()) {
                Expression expr = returnStmt.getExpression().get();
                
                /* 注释掉递归处理，让JavaParser的访问者模式来处理
                // If returning a new object creation
                if (expr instanceof ObjectCreationExpr) {
                    processObjectCreation((ObjectCreationExpr) expr);
                }
                // If returning a method call
                else if (expr instanceof MethodCallExpr) {
                    processMethodCall((MethodCallExpr) expr);
                }
                // If returning a field access
                else if (expr instanceof FieldAccessExpr) {
                    processFieldAccess((FieldAccessExpr) expr);
                }
                // If returning a cast expression
                else if (expr instanceof CastExpr) {
                    processCastExpr((CastExpr) expr);
                }
                */
                // 处理返回表达式中的特定类型
                // 对于嵌套的表达式，它们会在各自的visit方法中处理
                
                // If returning a variable name or field access
                if (expr instanceof NameExpr) {
                    String varName = expr.toString();
                    String varType = localVariableTypes.get(varName);
                    if (varType != null && isUserDefinedClass(varType)) {
                        addRelationshipOnce(varType, RelationshipType.USES, "return " + varType);
                    }
                }
                
                // 不需要手动调用expr.accept，super.visit会处理
            }
            
            // 恢复super.visit调用，确保子节点被访问
            super.visit(returnStmt, arg);
        }
        
        @Override
        public void visit(CastExpr castExpr, Void arg) {
            // 恢复对类型转换的处理，但避免重复处理
            // 只处理不是作为语句一部分的类型转换
            if (!(castExpr.getParentNode().isPresent() && 
                  castExpr.getParentNode().get() instanceof ExpressionStmt)) {
                processCastExpr(castExpr);
            }
            
            // 恢复super.visit调用，确保子节点被访问
            super.visit(castExpr, arg);
        }
        
        @Override
        public void visit(InstanceOfExpr instanceOfExpr, Void arg) {
            // When a class checks instanceof another type, it indicates a relationship
            String targetClass = resolveClassName(instanceOfExpr.getType().asString());
            if (isUserDefinedClass(targetClass)) {
                addRelationshipOnce(targetClass, RelationshipType.USES, "instanceof " + targetClass);
            }
            
            super.visit(instanceOfExpr, arg);
        }
        
        @Override
        public void visit(LambdaExpr lambdaExpr, Void arg) {
            // Process lambda parameters
            lambdaExpr.getParameters().forEach(param -> {
                // Parameter might be explicitly or implicitly typed
                if (param.getType() != null) {
                    String paramType = resolveClassName(param.getType().asString());
                    if (isUserDefinedClass(paramType)) {
                        addRelationshipOnce(paramType, RelationshipType.USES, "lambda parameter " + param.getNameAsString() + " of type " + paramType);
                    }
                }
            });
            
            // Visit the lambda body to find relationships within it
            super.visit(lambdaExpr, arg);
        }
        
        @Override
        public void visit(ObjectCreationExpr creation, Void arg) {
            // 恢复对对象创建的处理，但避免重复处理
            // 只处理不是作为语句一部分的对象创建
            if (!(creation.getParentNode().isPresent() && 
                  creation.getParentNode().get() instanceof ExpressionStmt)) {
                processObjectCreation(creation);
            }
            
            // 恢复super.visit调用，确保子节点被访问
            super.visit(creation, arg);
        }
        
        @Override
        public void visit(ExpressionStmt stmt, Void arg) {
            // Process expressions in statements (like method calls)
            Expression expr = stmt.getExpression();
            
            // If it's a method call (e.g., "addLineItem(cartItem);")
            if (expr instanceof MethodCallExpr) {
                MethodCallExpr methodCall = (MethodCallExpr) expr;
                
                // Process method arguments
                for (Expression argument : methodCall.getArguments()) {
                    // If the argument is a variable name, try to determine its type
                    if (argument.isNameExpr()) {
                        String varName = argument.toString();
                        // Check if we know this variable's type
                        String varType = localVariableTypes.get(varName);
                        if (varType != null && isUserDefinedClass(varType)) {
                            // Add relationship to the variable's type
                            addRelationshipOnce(varType, RelationshipType.USES, "variable " + sourceClass + "." + varName + " of type " + varType);
                        }
                    }
                    // For other argument types, process them directly
                    // else if (argument instanceof MethodCallExpr) {
                    //     processMethodCall((MethodCallExpr) argument);
                    // }
                    // else if (argument instanceof FieldAccessExpr) {
                    //     processFieldAccess((FieldAccessExpr) argument);
                    // }
                    // else if (argument instanceof CastExpr) {
                    //     processCastExpr((CastExpr) argument);
                    // }
                    // else if (argument instanceof ObjectCreationExpr) {
                    //     processObjectCreation((ObjectCreationExpr) argument);
                    // }
                    // else {
                    //     // For any other types, let the visitor handle them
                    //     argument.accept(this, arg);
                    // }
                    // 不需要手动处理其他类型的参数，super.visit会处理
                }
                
                // 只处理顶层方法调用（直接作为语句的方法调用）
                // 嵌套的方法调用会在visit(MethodCallExpr)中处理
                processMethodCall(methodCall);
            }
            // // For other types of expressions in statements
            // else {
            //     expr.accept(this, arg);
            // }
            // 不需要手动处理其他类型的表达式，super.visit会处理
            
            // 恢复super.visit调用，确保子节点被访问
            super.visit(stmt, arg);
        }
        
        @Override
        public void visit(ConstructorDeclaration constructor, Void arg) {
            // Clear tracking maps when entering a new constructor
            localVariableTypes.clear();
            // addedRelationships.clear(); // No longer needed as we count all relationships
            
            // Track parameter types
            constructor.getParameters().forEach(param -> {
                String paramName = param.getNameAsString();
                String paramType = resolveClassName(param.getType().asString());
                localVariableTypes.put(paramName, paramType);
                
                // Add USES relationship for each parameter type
                if (isUserDefinedClass(paramType)) {
                    addRelationshipOnce(paramType, RelationshipType.USES, "constructor " + sourceClass + " parameter " + paramName + " of type " + paramType);
                }
            });
            
            // Visit constructor body
            super.visit(constructor, arg);
        }
        
        // Helper methods to process different expression types without causing name clashes
        private void processMethodCall(MethodCallExpr methodCall) {
            String methodName = methodCall.getNameAsString();
            // Get parameter types for method signature matching
            List<String> parameterTypes = new ArrayList<>();
            for (Expression arg : methodCall.getArguments()) {
                // Try to determine parameter type from the expression
                String paramType = getExpressionType(arg);
                parameterTypes.add(paramType);
            }
            
            // Create method signature for matching
            MethodSignature methodSignature = new MethodSignature(methodName, parameterTypes);
            
            // Check if the method call has a scope (receiver)
            if (methodCall.getScope().isPresent()) {
                Expression scope = methodCall.getScope().get();
                
                // Case 1: Static method call (C.m())
                if (scope.isNameExpr() && Character.isUpperCase(scope.toString().charAt(0)) && 
                    !localVariableTypes.containsKey(scope.toString())) {
                    
                    String className = resolveClassName(scope.toString());
                    if (isUserDefinedClass(className)) {
                        // Static calls only need direct relationship
                        addRelationshipOnce(className, RelationshipType.CALLS, 
                            "Static: " + scope + "." + methodName + getParamTypesString(parameterTypes));
                    }
                }
                // Case 2: Special method call (super.m(), private methods)
                else if (isSpecialCall(methodCall)) {
                    String receiverType = getReceiverType(scope);
                    if (receiverType != null && isUserDefinedClass(receiverType)) {
                        // For special calls, use dispatch to find the actual implementation
                        Set<String> dispatchResults = dispatch(receiverType, methodSignature);
                        for (String targetClass : dispatchResults) {
                            addRelationshipOnce(targetClass, RelationshipType.CALLS, 
                                "Special: " + scope + "." + methodName + getParamTypesString(parameterTypes) + " -> " + targetClass);
                        }
                    }
                }
                // Case 3: Virtual method call (obj.m())
                else if (scope.isNameExpr()) {
                    String varName = scope.toString();
                    String declaredType = localVariableTypes.get(varName);
                    
                    if (declaredType != null && isUserDefinedClass(declaredType)) {
                        // Apply CHA algorithm for virtual calls
                        
                        // First find the actual method defining class using dispatch
                        Set<String> dispatchResults = dispatch(declaredType, methodSignature);
                        
                        // If dispatch found a method implementation, use it
                        if (!dispatchResults.isEmpty()) {
                            for (String definingClass : dispatchResults) {
                                // Add call relationship to the class that actually defines the method
                                addRelationshipOnce(definingClass, RelationshipType.CALLS, 
                                    "CHA(defined): " + varName + "." + methodName + getParamTypesString(parameterTypes) + " -> " + definingClass);
                            }
                        } else {
                            // Fallback: add direct call to declared type if dispatch didn't find anything
                            addRelationshipOnce(declaredType, RelationshipType.CALLS, 
                                varName + "." + methodName + getParamTypesString(parameterTypes));
                        }
                        
                        // Find all possible runtime types (declared type and all subclasses)
                        Set<String> possibleTypes = new HashSet<>();
                        possibleTypes.add(declaredType);
                        
                        // If it's an interface or abstract class, find all implementations
                        if (isInterfaceOrAbstractClass(declaredType)) {
                            possibleTypes.addAll(findAllImplementations(declaredType));
                        } 
                        // Otherwise find all subclasses
                        else {
                            possibleTypes.addAll(findAllSubclasses(declaredType));
                        }
                        
                        // For each possible runtime type, check if it overrides the method
                        for (String type : possibleTypes) {
                            if (!type.equals(declaredType)) { // Skip declared type (already handled)
                                // Only add relationship if this class actually overrides the method
                                if (hasOwnMethod(type, methodSignature)) {
                                    addRelationshipOnce(type, RelationshipType.CALLS, 
                                        "CHA(override): " + varName + "." + methodName + getParamTypesString(parameterTypes) + " -> " + type);
                                }
                            }
                        }
                    }
                }
            }
            
            // Process method arguments
            for (Expression argument : methodCall.getArguments()) {
                // If argument is a variable name, check its type
                if (argument.isNameExpr()) {
                    String varName = argument.toString();
                    String varType = localVariableTypes.get(varName);
                    if (varType != null && isUserDefinedClass(varType)) {
                        addRelationshipOnce(varType, RelationshipType.USES, 
                            methodCall.getNameAsString() + "(" + varName + ")");
                    }
                }
                /* 注释掉递归处理，让JavaParser的访问者模式来处理
                // Process other argument types
                else if (argument instanceof ObjectCreationExpr) {
                    processObjectCreation((ObjectCreationExpr) argument);
                }
                else if (argument instanceof MethodCallExpr) {
                    processMethodCall((MethodCallExpr) argument);
                }
                else if (argument instanceof FieldAccessExpr) {
                    processFieldAccess((FieldAccessExpr) argument);
                }
                else if (argument instanceof CastExpr) {
                    processCastExpr((CastExpr) argument);
                }
                */
            }
        }
        
        /**
         * Get the type of an expression
         */
        private String getExpressionType(Expression expr) {
            if (expr.isNameExpr()) {
                // If it's a variable name, get its type from local variables map
                String varName = expr.toString();
                return localVariableTypes.getOrDefault(varName, "Object");
            } else if (expr instanceof LiteralExpr) {
                // Handle literals
                if (expr instanceof StringLiteralExpr) {
                    return "java.lang.String";
                } else if (expr instanceof IntegerLiteralExpr) {
                    return "int";
                } else if (expr instanceof LongLiteralExpr) {
                    return "long";
                } else if (expr instanceof DoubleLiteralExpr) {
                    return "double";
                } else if (expr instanceof BooleanLiteralExpr) {
                    return "boolean";
                } else if (expr instanceof CharLiteralExpr) {
                    return "char";
                } else if (expr instanceof NullLiteralExpr) {
                    return "null";
                }
            } else if (expr instanceof MethodCallExpr) {
                // For method calls, we'd need to track return types
                // This is complex and would require more context
                return "Object";
            } else if (expr instanceof ObjectCreationExpr) {
                // For object creation, use the created type
                ObjectCreationExpr creation = (ObjectCreationExpr) expr;
                return creation.getType().asString();
            }
            
            // Default fallback
            return "Object";
        }
        
        /**
         * Format parameter types for display in relationship descriptions
         */
        private String getParamTypesString(List<String> paramTypes) {
            if (paramTypes == null || paramTypes.isEmpty()) {
                return "()";
            }
            
            StringBuilder sb = new StringBuilder("(");
            for (int i = 0; i < paramTypes.size(); i++) {
                if (i > 0) {
                    sb.append(", ");
                }
                // Get simple name for readability
                String type = paramTypes.get(i);
                if (type == null) {
                    sb.append("?");
                    continue;
                }
                int lastDot = type.lastIndexOf('.');
                if (lastDot > 0) {
                    type = type.substring(lastDot + 1);
                }
                sb.append(type);
            }
            sb.append(")");
            return sb.toString();
        }
        
        /**
         * Class to represent a method signature (name + parameter types)
         */
        private class MethodSignature {
            private final String name;
            private final List<String> parameterTypes;
            
            public MethodSignature(String name, List<String> parameterTypes) {
                this.name = name;
                this.parameterTypes = parameterTypes;
            }
            
            public String getName() {
                return name;
            }
            
            public List<String> getParameterTypes() {
                return parameterTypes;
            }
            
            @Override
            public boolean equals(Object obj) {
                if (this == obj) return true;
                if (obj == null || getClass() != obj.getClass()) return false;
                MethodSignature that = (MethodSignature) obj;
                
                // Compare method names
                if (!name.equals(that.name)) return false;
                
                // If parameter count differs, methods are different
                if (parameterTypes.size() != that.parameterTypes.size()) return false;
                
                // Compare parameter types
                for (int i = 0; i < parameterTypes.size(); i++) {
                    // Simple string comparison for now
                    // In a more sophisticated implementation, we'd check type compatibility
                    if (!parameterTypes.get(i).equals(that.parameterTypes.get(i))) {
                        return false;
                    }
                }
                
                return true;
            }
            
            @Override
            public int hashCode() {
                int result = name.hashCode();
                result = 31 * result + parameterTypes.hashCode();
                return result;
            }
            
            @Override
            public String toString() {
                StringBuilder sb = new StringBuilder();
                sb.append(name).append("(");
                for (int i = 0; i < parameterTypes.size(); i++) {
                    if (i > 0) {
                        sb.append(", ");
                    }
                    sb.append(parameterTypes.get(i));
                }
                sb.append(")");
                return sb.toString();
            }
        }
        
        /**
         * Check if a method call is a special call (constructor, super call, private method)
         */
        private boolean isSpecialCall(MethodCallExpr methodCall) {
            String methodName = methodCall.getNameAsString();
            
            // Constructor call
            if (methodName.equals("this") || methodName.equals("super")) {
                return true;
            }
            
            // super.method() call
            if (methodCall.getScope().isPresent() && 
                methodCall.getScope().get().toString().equals("super")) {
                return true;
            }
            
            // Private method call
            if (methodCall.getScope().isPresent()) {
                Expression scope = methodCall.getScope().get();
                String receiverType = getReceiverType(scope);
                
                if (receiverType != null) {
                    // Check if the method is private in the receiver type
                    ClassDetails details = graph.getClassDetail(receiverType);
                    if (details != null) {
                        for (MethodInfo method : details.getMethods()) {
                            if (method.getName().equals(methodName) && method.isPrivate()) {
                                return true;
                            }
                        }
                    }
                }
            }
            
            return false;
        }
        
        /**
         * Get the type of the receiver expression
         */
        private String getReceiverType(Expression scope) {
            if (scope.isNameExpr()) {
                String name = scope.toString();
                
                // If it's super keyword
                if (name.equals("super")) {
                    // Get the superclass of the current class
                    ClassNode currentClass = graph.getNodes().get(sourceClass);
                    if (currentClass != null) {
                        for (Relationship rel : currentClass.getRelationships()) {
                            if (rel.getType() == RelationshipType.EXTENDS) {
                                return rel.getTargetClass();
                            }
                        }
                    }
                }
                // If it's this keyword
                else if (name.equals("this")) {
                    return sourceClass;
                }
                // If it's a variable
                else {
                    return localVariableTypes.get(name);
                }
            }
            // If it's a class name (static call)
            else if (scope.toString().contains(".") || Character.isUpperCase(scope.toString().charAt(0))) {
                return resolveClassName(scope.toString());
            }
            
            return null;
        }
        
        /**
         * Implement CHA's Dispatch function to find the actual method implementation
         * Updated to use method signature instead of just method name
         */
        private Set<String> dispatch(String className, MethodSignature methodSignature) {
            Set<String> result = new HashSet<>();
            
            // If the class doesn't exist in our graph, return empty set
            if (!graph.getNodes().containsKey(className)) {
                return result;
            }
            
            // Check if current class contains non-abstract method with this signature
            if (hasNonAbstractMethod(className, methodSignature)) {
                result.add(className);
                return result; // Found the implementation, no need to check superclass
            }
            
            // If not found in current class, recursively check superclass
            String parentClass = getSuperclass(className);
            if (parentClass != null) {
                // Recursively check parent class
                Set<String> parentResult = dispatch(parentClass, methodSignature);
                if (!parentResult.isEmpty()) {
                    return parentResult; // Found in parent class
                }
            }
            
            // If still not found and this is an interface, check Object class for default methods
            if (isInterfaceOrAbstractClass(className) && !methodSignature.getName().equals("<init>")) {
                // For interface methods, check if java.lang.Object provides an implementation
                if (isCommonObjectMethod(methodSignature.getName())) {
                    result.add("java.lang.Object");
                }
            }
            
            return result;
        }
        
        /**
         * Check if a method name is a common method from Object class
         */
        private boolean isCommonObjectMethod(String methodName) {
            return methodName.equals("toString") || 
                   methodName.equals("equals") || 
                   methodName.equals("hashCode") ||
                   methodName.equals("getClass") ||
                   methodName.equals("clone") ||
                   methodName.equals("notify") ||
                   methodName.equals("notifyAll") ||
                   methodName.equals("wait");
        }
        
        /**
         * Check if a class has a non-abstract method with the given signature
         */
        private boolean hasNonAbstractMethod(String className, MethodSignature methodSignature) {
            ClassDetails details = graph.getClassDetail(className);
            if (details != null) {
                for (MethodInfo method : details.getMethods()) {
                    if (method.getName().equals(methodSignature.getName()) && 
                        !method.isAbstract() &&
                        parametersMatch(method.getParameterTypes(), methodSignature.getParameterTypes())) {
                        return true;
                    }
                }
            }
            return false;
        }
        
        /**
         * Check if parameter types match
         */
        private boolean parametersMatch(List<String> methodParams, List<String> signatureParams) {
            // If parameter count differs, methods are different
            if (methodParams.size() != signatureParams.size()) {
                return false;
            }
            
            // In a simple implementation, we just check if parameter counts match
            // In a more sophisticated implementation, we'd check type compatibility
            // For now, this is good enough since we're focusing on method overriding
            return true;
        }
        
        
        
        private void processFieldAccess(FieldAccessExpr fieldAccess) {
            if (fieldAccess.getScope() != null) {
                Expression scope = fieldAccess.getScope();
                
                if (scope.isNameExpr()) {
                    String varName = scope.toString();
                    String varType = localVariableTypes.get(varName);
                    if (varType != null && isUserDefinedClass(varType)) {
                        // Add relationship to the variable's type (only once per method)
                        addRelationshipOnce(varType, RelationshipType.USES, 
                            varName + "." + fieldAccess.getNameAsString());
                    }
                }
                /* 注释掉递归处理，让JavaParser的访问者模式来处理
                // If the scope is a method call (e.g., "getCart().getItems()")
                else if (scope instanceof MethodCallExpr) {
                    processMethodCall((MethodCallExpr) scope);
                }
                // If the scope is another field access (e.g., "cart.item.id")
                else if (scope instanceof FieldAccessExpr) {
                    processFieldAccess((FieldAccessExpr) scope);
                }
                */
            }
        }
        
        private void processCastExpr(CastExpr castExpr) {
            String targetClass = resolveClassName(castExpr.getType().asString());
            if (isUserDefinedClass(targetClass)) {
                addRelationshipOnce(targetClass, RelationshipType.USES, 
                    "(" + castExpr.getType().asString() + ") " + castExpr.getExpression());
            }
        }
        
        private void processObjectCreation(ObjectCreationExpr creation) {
            String targetClass = resolveClassName(creation.getType().getNameAsString());
            if (isUserDefinedClass(targetClass)) {
                addRelationshipOnce(targetClass, RelationshipType.CREATES, 
                    "new " + creation.getType().getNameAsString() + "()");
                addRelationshipOnce(targetClass, RelationshipType.USES, 
                    "new " + creation.getType().getNameAsString() + "()");
            }
        }
        
        /**
         * Add a relationship, ensuring we don't add the same relationship multiple times in a method
         */
        private void addRelationshipOnce(String targetClass, RelationshipType type, String codeStatement) {
            // Validate target class before adding relationship
            if (targetClass == null || targetClass.isEmpty()) {
                return; // Skip adding relationship if the target is null or empty
            }
            
            // Process generic types correctly
            if (targetClass.contains("<")) {
                targetClass = extractBaseType(targetClass);
                
                // If after extraction we still don't have a valid class, skip
                if (targetClass == null || !isValidClassName(targetClass)) {
                    return;
                }
            }
            
            // Only add relationships to user-defined classes
            if (!isUserDefinedClass(targetClass)) {
                return; // Skip non-user-defined classes
            }
            
            // Try to resolve to fully qualified name if it's a simple name
            if (!targetClass.contains(".")) {
                String resolvedTarget = resolveClassName(targetClass);
                if (resolvedTarget == null) {
                    return; // Skip if we can't resolve to a fully qualified name
                }
                targetClass = resolvedTarget;
            }
            
            // Always add relationship and let graph handle counting
            graph.addRelationship(sourceClass, targetClass, type);
            
            // Always track the code statement that created this relationship
            // Use a Set instead of a List to automatically deduplicate statements
            String fullKey = sourceClass + ":" + type.toString() + ":" + targetClass;
            relationshipStatements.computeIfAbsent(fullKey, k -> new LinkedHashSet<>())
                .add(codeStatement);
        }
        
        // Overload for backward compatibility
        private void addRelationshipOnce(String targetClass, RelationshipType type) {
            addRelationshipOnce(targetClass, type, "Unknown source location");
        }
        
        /**
         * Check if a class has a non-abstract method with the given name
         */
        private boolean hasNonAbstractMethod(String className, String methodName) {
            ClassDetails details = graph.getClassDetail(className);
            if (details != null) {
                for (MethodInfo method : details.getMethods()) {
                    if (method.getName().equals(methodName) && !method.isAbstract()) {
                        return true;
                    }
                }
            }
            return false;
        }
        
        /**
         * Get the direct superclass of a class
         */
        private String getSuperclass(String className) {
            ClassNode node = graph.getNodes().get(className);
            if (node != null) {
                for (Relationship rel : node.getRelationships()) {
                    if (rel.getType() == RelationshipType.EXTENDS) {
                        return rel.getTargetClass();
                    }
                }
            }
            return null;
        }
        
        /**
         * Check if a class is an interface or abstract class
         */
        private boolean isInterfaceOrAbstractClass(String className) {
            ClassDetails details = graph.getClassDetail(className);
            if (details != null) {
                // Check for interface or abstract class annotations
                for (String annotation : details.getAnnotations()) {
                    if (annotation.contains("@Interface") || annotation.contains("abstract")) {
                        return true;
                    }
                }
                
                // Check methods for abstract methods
                for (MethodInfo method : details.getMethods()) {
                    if (method.isAbstract()) {
                        return true;
                    }
                }
            }
            
            // Infer from class name
            return className.contains("Interface") || className.endsWith("able");
        }
        
        /**
         * Find all implementations of an interface or abstract class
         */
        private Set<String> findAllImplementations(String interfaceOrAbstractClass) {
            Set<String> result = new HashSet<>();
            
            // Find all classes that implement/extend this interface/abstract class
            for (ClassNode node : graph.getNodes().values()) {
                for (Relationship rel : node.getRelationships()) {
                    if ((rel.getType() == RelationshipType.IMPLEMENTS || 
                         rel.getType() == RelationshipType.EXTENDS) && 
                        rel.getTargetClass().equals(interfaceOrAbstractClass)) {
                        String implementingClass = node.getClassName();
                        result.add(implementingClass);
                        
                        // Also add subclasses of this implementing class
                        result.addAll(findAllSubclasses(implementingClass));
                    }
                }
            }
            
            return result;
        }
        
        /**
         * Find all subclasses of a class
         */
        private Set<String> findAllSubclasses(String className) {
            Set<String> result = new HashSet<>();
            
            // Find all direct subclasses
            for (ClassNode node : graph.getNodes().values()) {
                for (Relationship rel : node.getRelationships()) {
                    if (rel.getType() == RelationshipType.EXTENDS && 
                        rel.getTargetClass().equals(className)) {
                        String subclass = node.getClassName();
                        result.add(subclass);
                        
                        // Recursively find subclasses of this subclass
                        result.addAll(findAllSubclasses(subclass));
                    }
                }
            }
            
            return result;
        }

        /**
         * Check if a class directly defines a method (not inheriting from parent)
         */
        private boolean hasOwnMethod(String className, String methodName) {
            ClassDetails details = graph.getClassDetail(className);
            if (details != null) {
                for (MethodInfo method : details.getMethods()) {
                    if (method.getName().equals(methodName)) {
                        return true;
                    }
                }
            }
            return false;
        }

        /**
         * Check if a class directly defines a method with the given signature
         */
        private boolean hasOwnMethod(String className, MethodSignature methodSignature) {
            ClassDetails details = graph.getClassDetail(className);
            if (details != null) {
                for (MethodInfo method : details.getMethods()) {
                    if (method.getName().equals(methodSignature.getName()) &&
                        parametersMatch(method.getParameterTypes(), methodSignature.getParameterTypes())) {
                        return true;
                    }
                }
            }
            return false;
        }
    }
} 